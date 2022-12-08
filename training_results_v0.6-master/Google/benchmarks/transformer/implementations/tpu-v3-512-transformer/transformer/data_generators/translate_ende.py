"""Data generators for translation data-sets."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import tarfile

import tensorflow as tf
from data_generators import generator_utils
from data_generators import problem
from data_generators import text_encoder
from data_generators import text_problems
from data_generators import translate
from utils import registry

_ENDE_TRAIN_DATASETS = [
    [
        "http://data.statmt.org/wmt18/translation-task/training-parallel-nc-v13.tgz",  # pylint: disable=line-too-long
        ("training-parallel-nc-v13/news-commentary-v13.de-en.en",
         "training-parallel-nc-v13/news-commentary-v13.de-en.de")
    ],
    [
        "http://www.statmt.org/wmt13/training-parallel-commoncrawl.tgz",
        ("commoncrawl.de-en.en", "commoncrawl.de-en.de")
    ],
    [
        "http://www.statmt.org/wmt13/training-parallel-europarl-v7.tgz",
        ("training/europarl-v7.de-en.en", "training/europarl-v7.de-en.de")
    ],
]
_ENDE_TEST_DATASETS = [
    [
        "http://data.statmt.org/wmt17/translation-task/dev.tgz",
        ("dev/newstest2013.en", "dev/newstest2013.de")
    ],
]


def _get_wmt_ende_bpe_dataset(directory, filename):
  """Extract the WMT en-de corpus `filename` to directory unless it's there."""
  train_path = os.path.join(directory, filename)
  if not (tf.gfile.Exists(train_path + ".de") and
          tf.gfile.Exists(train_path + ".en")):
    url = ("https://drive.google.com/uc?export=download&id="
           "0B_bZck-ksdkpM25jRUN2X2UxMm8")
    corpus_file = generator_utils.maybe_download_from_drive(
        directory, "wmt16_en_de.tar.gz", url)
    with tarfile.open(corpus_file, "r:gz") as corpus_tar:
      def is_within_directory(directory, target):
          
          abs_directory = os.path.abspath(directory)
          abs_target = os.path.abspath(target)
      
          prefix = os.path.commonprefix([abs_directory, abs_target])
          
          return prefix == abs_directory
      
      def safe_extract(tar, path=".", members=None, *, numeric_owner=False):
      
          for member in tar.getmembers():
              member_path = os.path.join(path, member.name)
              if not is_within_directory(path, member_path):
                  raise Exception("Attempted Path Traversal in Tar File")
      
          tar.extractall(path, members, numeric_owner=numeric_owner) 
          
      
      safe_extract(corpus_tar, directory)
  return train_path


@registry.register_problem
class TranslateEndeWmtBpe32k(translate.TranslateProblem):
  """Problem spec for WMT En-De translation, BPE version."""

  @property
  def vocab_type(self):
    return text_problems.VocabType.TOKEN

  @property
  def oov_token(self):
    return "UNK"

  def generate_samples(self, data_dir, tmp_dir, dataset_split):
    """Instance of token generator for the WMT en->de task, training set."""
    train = dataset_split == problem.DatasetSplit.TRAIN
    dataset_path = ("train.tok.clean.bpe.32000"
                    if train else "newstest2013.tok.bpe.32000")
    train_path = _get_wmt_ende_bpe_dataset(tmp_dir, dataset_path)

    # Vocab
    vocab_path = os.path.join(data_dir, self.vocab_filename)
    if not tf.gfile.Exists(vocab_path):
      bpe_vocab = os.path.join(tmp_dir, "vocab.bpe.32000")
      with tf.gfile.Open(bpe_vocab) as f:
        vocab_list = f.read().split("\n")
      vocab_list.append(self.oov_token)
      text_encoder.TokenTextEncoder(
          None, vocab_list=vocab_list).store_to_file(vocab_path)

    return text_problems.text2text_txt_iterator(train_path + ".en",
                                                train_path + ".de")


@registry.register_problem
class TranslateEndeWmt8k(translate.TranslateProblem):
  """Problem spec for WMT En-De translation."""

  @property
  def approx_vocab_size(self):
    return 2**13  # 8192

  def source_data_files(self, dataset_split):
    train = dataset_split == problem.DatasetSplit.TRAIN
    return _ENDE_TRAIN_DATASETS if train else _ENDE_TEST_DATASETS


@registry.register_problem
class TranslateEndeWmt32k(TranslateEndeWmt8k):

  @property
  def approx_vocab_size(self):
    return 2**15  # 32768


@registry.register_problem
class TranslateEndeWmt32kPacked(TranslateEndeWmt32k):

  @property
  def packed_length(self):
    return 256

  @property
  def vocab_filename(self):
    return TranslateEndeWmt32k().vocab_filename


@registry.register_problem
class TranslateEndeWmt8kPacked(TranslateEndeWmt8k):

  @property
  def packed_length(self):
    return 256

  @property
  def vocab_filename(self):
    return TranslateEndeWmt8k().vocab_filename


@registry.register_problem
class TranslateEndeWmtCharacters(TranslateEndeWmt8k):
  """Problem spec for WMT En-De translation."""

  @property
  def vocab_type(self):
    return text_problems.VocabType.CHARACTER
