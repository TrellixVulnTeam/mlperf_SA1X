# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =============================================================================

"""momentum"""
import mindspore.common.dtype as mstype
from mindspore.common.initializer import initializer
from mindspore.common.parameter import Parameter
from mindspore.common.parameter import ParameterTuple
from mindspore.common.tensor import Tensor
from mindspore.nn.optim.optimizer import Optimizer
from mindspore.ops import functional as F, composite as C, operations as P
from mindspore.parallel._utils import _get_device_num, _get_mirror_mean
from model.grad_reducer_thor import DistributedGradReducerThor

momentum_opt = C.MultitypeFuncGraph("momentum_opt")


@momentum_opt.register("Function", "Tensor", "Tensor", "Tensor", "Tensor", "Tensor")
def _tensor_run_opt_ext(opt, learning_rate, momentum, gradient, weight, moment):
    """Apply momentum optimizer to the weight parameter using Tensor."""
    success = True
    success = F.depend(success, opt(weight, moment, learning_rate, gradient, momentum))
    return success


op_add = P.AddN()
apply_decay = C.MultitypeFuncGraph("apply_decay")


@apply_decay.register("Number", "Bool", "Tensor", "Tensor")
def _tensor_apply_decay(weight_decay, if_apply, weight, gradient):
    """Get grad with weight_decay."""
    if if_apply:
        return op_add((weight * weight_decay, gradient))
    return gradient


class THOR(Optimizer):
    """THOR"""
    def __init__(self, params, learning_rate, momentum, matrix_A, matrix_G, A_inv_max, G_inv_max, weight_decay=0.0,
                 loss_scale=1.0, batch_size=32.0,
                 decay_filter=lambda x: x.name not in []):
        super(THOR, self).__init__(learning_rate, params, weight_decay, loss_scale)
        if isinstance(momentum, float) and momentum < 0.0:
            raise ValueError("momentum should be at least 0.0, but got momentum {}".format(momentum))
        self.momentum = Parameter(Tensor(momentum, mstype.float32), name="momentum")
        self.params = self.parameters
        self.moments = self.params.clone(prefix="moments", init='zeros')
        self.hyper_map = C.HyperMap()
        self.opt = P.ApplyMomentum()
        self.matrix_A = ParameterTuple(matrix_A)
        self.matrix_G = ParameterTuple(matrix_G)
        self.A_inv_max = ParameterTuple(A_inv_max)
        self.G_inv_max = ParameterTuple(G_inv_max)
        self.cube_matmul_left = P.CusMatMulCubeFraczLeftCast()
        self.cube_matmul_left_fc = P.CusMatMulCubeDenseLeft()
        self.cube_matmul_right_fc = P.CusMatMulCubeDenseRight()
        self.cube_matmul_right_mul = P.CusMatMulCubeFraczRightMul()
        self.transpose = P.Transpose()
        self.shape = P.Shape()
        self.reshape = P.Reshape()
        self.mul = P.Mul()
        self.weight_idx = []
        for i in range(len(self.params)):
            if "conv" in self.params[i].name or "end_point" in self.params[i].name:
                self.weight_idx.append(i)
        self.weight_idx.append(len(self.params))
        self.feature_map = [1.0 / 12544, 1.0 / 3136, 1.0 / 3136, 1.0 / 3136, 1.0 / 3136, 1.0 / 3136, 1.0 / 3136,
                            1.0 / 3136, 1.0 / 3136, 1.0 / 3136, 1.0 / 3136, 1.0 / 3136,
                            1.0 / 784, 1.0 / 784, 1.0 / 784, 1.0 / 784, 1.0 / 784, 1.0 / 784, 1.0 / 784, 1.0 / 784,
                            1.0 / 784, 1.0 / 784, 1.0 / 784, 1.0 / 784, 1.0 / 784,
                            1.0 / 196, 1.0 / 196, 1.0 / 196, 1.0 / 196, 1.0 / 196, 1.0 / 196, 1.0 / 196, 1.0 / 196,
                            1.0 / 196, 1.0 / 196, 1.0 / 196, 1.0 / 196, 1.0 / 196, 1.0 / 196, 1.0 / 196, 1.0 / 196,
                            1.0 / 196, 1.0 / 196, 1.0 / 196,
                            1.0 / 49, 1.0 / 49, 1.0 / 49, 1.0 / 49, 1.0 / 49, 1.0 / 49, 1.0 / 49, 1.0 / 49, 1.0 / 49,
                            1.0]
        mean = _get_mirror_mean()
        degree = _get_device_num()
        self.grad_reducer_Amax = DistributedGradReducerThor(self.parameters, 2, mean, degree)
        self.grad_reducer_Gmax = DistributedGradReducerThor(self.parameters, 5, mean, degree)
        self.grad_reducer_A = DistributedGradReducerThor(self.parameters, 3, mean, degree)
        self.grad_reducer_G = DistributedGradReducerThor(self.parameters, 4, mean, degree)
        self.matrix_A_inv = ()
        self.matrix_G_inv = ()
        self.matrix_max_inv = ()

        for i in range(54):
            self.matrix_max_inv = self.matrix_max_inv + (
                Parameter(initializer(1, [1], mstype.float32), name="matrix_max" + str(i), requires_grad=False),)
        self.log = P.Log()
        self.exp = P.Exp()
        self.sqrt = P.Sqrt()
        self.matrix_max_inv = ParameterTuple(self.matrix_max_inv)
        self.assign = P.Assign()
        self.cast = P.Cast()
        self.thor = True
        self.weight_decay = weight_decay * loss_scale
        self.decay_flags = tuple(decay_filter(x) for x in self.parameters)

        self.conv_index = [
            0,
            1,2,3,6,7,8,9,12,13,14,
            17,18,19,22,23,24,25,28,29,30,33,34,35,
            38,39,40,43,44,45,46,49,50,51,54,55,56,59,60,61,64,65,66,
            69,70,71,74,75,76,77,80,81,82,
            85
        ]
        self.batch_size = batch_size
        self.bn_index = [3,7,10,13,17,20,23,26,30,33,36,39,42,45,49,52]
        self.bn_gradient_index = [
            -1,-1,-1,
            4,
            -1,-1,-1,
            10,
            -1,-1,
            15,
            -1,-1,
            20,
            -1,-1,-1,
            26,
            -1,-1,
            31,
            -1,-1,
            36,
            -1,-1,
            41,
            -1,-1,-1,
            47,
            -1,-1,
            52,
            -1,-1,
            57,
            -1,-1,
            62,
            -1,-1,
            67,
            -1,-1,
            72,
            -1,-1,-1,
            78,
            -1,-1,
            83
        ]

    def construct(self, gradients):
        params = self.params
        moments = self.moments
        if self.thor: # 二阶子图处理流程
            matrix_A_allreduce = ()
            matrix_G_allreduce = ()
            matrix_A_max_allreduce = ()
            matrix_G_max_allreduce = ()
            for i in range(54):
                g = gradients[self.conv_index[i]]
                matrix_A = self.matrix_A[i]
                matrix_G = self.matrix_G[i]
                A_max = self.A_inv_max[i]
                G_max = self.G_inv_max[i]
                matrix_A = F.depend(matrix_A, g)
                matrix_G = F.depend(matrix_G, g)
                A_max = F.depend(A_max, g)
                G_max = F.depend(G_max, g)
                matrix_A_allreduce = matrix_A_allreduce + (matrix_A,)
                matrix_G_allreduce = matrix_G_allreduce + (matrix_G,)
                matrix_A_max_allreduce = matrix_A_max_allreduce + (A_max,)
                matrix_G_max_allreduce = matrix_G_max_allreduce + (G_max,)
            matrix_A_allreduce = self.grad_reducer_A(matrix_A_allreduce)
            matrix_G_allreduce = self.grad_reducer_G(matrix_G_allreduce)
            matrix_A_max_allreduce = self.grad_reducer_Amax(matrix_A_max_allreduce)
            matrix_G_max_allreduce = self.grad_reducer_Gmax(matrix_G_max_allreduce)
            if self.batch_size == 256:
                new_grads = (gradients[0], )
                start_index = 1
            else:
                new_grads = ()
                start_index = 0
            for i in range(start_index, 54):
                # g = gradients[i * 3] # 原本梯度排列为weight，gamma，beta
                g = gradients[self.conv_index[i]]
                temp_a = matrix_A_allreduce[i]
                temp_g = matrix_G_allreduce[i]
                temp_a = self.cast(temp_a, mstype.float32)
                temp_g = self.cast(temp_g, mstype.float32)
                matrix_A_inv_max = self.log(matrix_A_max_allreduce[i])
                matrix_A_inv_max = self.mul(matrix_A_inv_max, -1)
                matrix_A_inv_max = self.exp(matrix_A_inv_max)
                temp_a = self.mul(temp_a, matrix_A_inv_max)
                matrix_G_inv_max = self.log(matrix_G_max_allreduce[i])
                matrix_G_inv_max = self.mul(matrix_G_inv_max, -1)
                matrix_G_inv_max = self.exp(matrix_G_inv_max)
                temp_g = self.mul(temp_g, matrix_G_inv_max)
                temp_max = self.mul(matrix_A_max_allreduce[i], matrix_G_max_allreduce[i])
                temp_max = self.mul(temp_max, self.feature_map[i])

                if i == 53: # 区分fc和卷积算子
                    g = self.cube_matmul_left_fc(temp_g, g)
                    g = self.cube_matmul_right_fc(g, temp_a, temp_max)
                else:
                    g = self.cube_matmul_left(temp_g, g)
                    g = self.cube_matmul_right_mul(g, temp_a, temp_max)
                # 计算得到的二阶信息矩阵赋值为parameter，给一阶用
                fake_A = self.assign(self.matrix_A[i], temp_a)
                fake_G = self.assign(self.matrix_G[i], temp_g)
                fake_max = self.assign(self.matrix_max_inv[i], temp_max)
                # 图上加个边
                g = F.depend(g, fake_A)
                g = F.depend(g, fake_G)
                g = F.depend(g, fake_max)
                # if i == 53: # 梯度放到tuple中，后面给momentum用来更新权重
                #     new_grads = new_grads + (g,)
                # else:
                #     new_grads = new_grads + (g, gradients[i * 3 + 1], gradients[i * 3 + 2])
                # if i in self.bn_index: #beta, gamma下标再算一下
                if i == 3 or i == 7 or i == 10 or i == 13 or i == 17 or i == 20 or i == 23 or i == 26 or i == 30 or i == 33 or i == 36 or i == 39 or i == 42 or i == 45 or i == 49 or i == 52:
                    new_grads = new_grads + (g, gradients[self.bn_gradient_index[i]], gradients[self.bn_gradient_index[i]+1])
                elif i == 53:
                    new_grads = new_grads + (g, gradients[86])
                else:
                    new_grads = new_grads + (g,)
            #gradients = new_grads + gradients[85]
            gradients = new_grads
        else: # 一阶子图处理流程
            if self.batch_size == 256:
                new_grads = (gradients[0], )
                start_index = 1
            else:
                new_grads = ()
                start_index = 0
            for i in range(start_index, 54):
                # g = gradients[i * 3]
                g = gradients[self.conv_index[i]]
                matrix_A = self.matrix_A[i]
                matrix_G = self.matrix_G[i]
                matrix_max = self.matrix_max_inv[i]
                matrix_A = F.depend(matrix_A, g)
                matrix_G = F.depend(matrix_G, g)
                matrix_max = F.depend(matrix_max, g)
                if i == 53:
                    g = self.cube_matmul_left_fc(matrix_G, g)
                    g = self.cube_matmul_right_fc(g, matrix_A, matrix_max)
                    # new_grads = new_grads + (g,)
                else:
                    g = self.cube_matmul_left(matrix_G, g)
                    g = self.cube_matmul_right_mul(g, matrix_A, matrix_max)
                    # new_grads = new_grads + (g, gradients[i * 3 + 1], gradients[i * 3 + 2])

                # if i in self.bn_index: #beta, gamma下标再算一下
                if i == 3 or i == 7 or i == 10 or i == 13 or i == 17 or i == 20 or i == 23 or i == 26 or i == 30 or i == 33 or i == 36 or i == 39 or i == 42 or i == 45 or i == 49 or i == 52:
                    new_grads = new_grads + (g, gradients[self.bn_gradient_index[i]], gradients[self.bn_gradient_index[i]+1])
                elif i == 53:
                    new_grads = new_grads + (g, gradients[86])
                else:
                    new_grads = new_grads + (g,)

            gradients = new_grads

        if self.weight_decay > 0:
            gradients = self.hyper_map(F.partial(apply_decay, self.weight_decay), self.decay_flags,
                                       params, gradients)
        gradients = self.scale_grad(gradients)
        lr = self.get_lr()
        success = self.hyper_map(F.partial(momentum_opt, self.opt, lr, self.momentum), gradients, params, moments)
        return success
