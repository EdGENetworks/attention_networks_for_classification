""""
TODO: Data pre-processing
	Own word vecs
	LASER sentences embeddings
	Embed label descriptions?
"""
import os
import pickle
import json
import configargparse
import gc
import torch
import tqdm
# import cProfile, pstats, io
# from pstats import SortKey

from data_utils.data_utils import process_dataset, get_data_loader, embeddings_from_docs, doc_to_fasttext
from text_class_learner import MultiLabelTextClassifier
from data_utils.eur_lex57k_to_doc import parse as eur_lex_parse
from data_utils.reuters_to_doc import parse as reuters_parse
from data_utils.csv_to_documents import sheet_to_docs as parse_sheet
from model import FastTextLearner
from layers import ULMFiTEncoder


# Mute Sklearn warnings
def warn(*args, **kwargs):
    pass

import warnings
warnings.warn = warn


if __name__ == '__main__':

	try:
		from apex import amp
		APEX_AVAILABLE = True
	except ModuleNotFoundError:
		APEX_AVAILABLE = False

	#########################################################################################
	# ARGUMENT PARSING
	#########################################################################################

	# parser = argparse.ArgumentParser()
	parser = configargparse.ArgParser(default_config_files=['.\\parameters.ini'])
	#  MAIN ARGUMENTS
	parser.add_argument('-c', '--my-config',
						required=False,
						is_config_file=True,
						help='config file path')
	parser.add_argument("--do_train",
						action='store_false',
						help="Whether to run training.")
	parser.add_argument("--do_eval",
						action='store_false',
						help="Whether to run eval on the dev set.")
	parser.add_argument("--pretrained_path",
						default=None,
						type=str,
						required=False,
						help="The path from where the pretrained model is to be retrieved.")


	#  TRAIN/EVAL ARGS
	parser.add_argument("--train_batch_size",
						required=True,
						type=int,
						help="Total batch size for training.")
	parser.add_argument("--eval_batch_size",
						required=True,
						type=int,
						help="Total batch size for eval.")
	parser.add_argument("--learning_rate",
						required=True,
						type=float,
						help="The initial learning rate for Adam.")
	parser.add_argument("--dropout",
						required=True,
						type=float,
						help="The initial learning rate for RAdam.")
	parser.add_argument("--num_train_epochs",
						required=True,
						type=int,
						help="Total number of training epochs to perform.")
	parser.add_argument("--eval_every",
						required=True,
						type=int,
						help="Nr of training updates before evaluating model")
	parser.add_argument("--K",
						required=True,
						type=int,
						help="Cut-off value for evaluation metrics")
	parser.add_argument("--weight_decay",
						required=True,
						type=float,
						help="L2 regularization term.")

	#  MODEL ARGS
	parser.add_argument("--model_name",
						type=str,
						required=True,
						help="Model to use. Options: HAN, HGRULWAN, HCapsNet & HCapsNetMultiHeadAtt")
	parser.add_argument("--binary_class",
						action='store_false',
						help="Whether model dataset as multi-class classification(cross-entropy based) or multi-label classification (multiple binary classification).")
	parser.add_argument("--use_glove",
						action='store_true',
						help="Whether to utilize additional GloVe embeddings next to FastText.")
	parser.add_argument("--word_encoder",
					   type=str,
					   required=True,
					   help="The path from where the class-names are to be retrieved.")
	parser.add_argument("--sent_encoder",
						type=str,
						required=True,
						help="The path from where the class-names are to be retrieved.")
	parser.add_argument("--embed_dim",
						type=int,
						help="Nr of dimensions of used word vectors")
	parser.add_argument("--word_hidden",
						type=int,
						help="Nr of hidden units word encoder. If GRU is used as encoder, the nr of hidden units is used for BOTH forward and backward pass, resulting in double resulting size.")
	parser.add_argument("--sent_hidden",
						type=int,
						help="Nr of hidden units sentence encoder. If GRU is used as encoder, the nr of hidden units is used for BOTH forward and backward pass, resulting in double resulting size.")

	# ulmfit options
	parser.add_argument("--ulmfit_pretrained_path",
						default=None,
						type=str,
						required=False,
						help="The path from where the pretrained language model is to be retrieved.")
	parser.add_argument("--dropout_factor",
						type=float,
						help="Multiplier for standard dropout values in ULMFiT.")

		# caps net options
	parser.add_argument("--dim_caps",
						type=int,
						help="Nr of dimensions of a capsule")
	parser.add_argument("--num_head_doc",
						default=5,
						type=int,
						help="Nr of dimensions of a capsule")
	parser.add_argument("--num_caps",
						type=int,
						help="Number of capsules in Primary Capsule Layer")
	parser.add_argument("--num_compressed_caps",
						type=int,
						help="Number of compressed capsules")
	parser.add_argument("--dropout_caps",
						type=float,
						help="Dropout to apply within CapsNet")
	#	DATA & PRE-PROCESSING ARGS
	parser.add_argument("--preprocess_all",
						action='store_true',
						help="Whether pre-process the dataset from a set of *.json files to a loadable dataset.")
	parser.add_argument("--create_doc_encodings",
						action='store_true',
						help="Whether to enrich the documents with an encoding for reconstruction.")

	parser.add_argument("--raw_data_dir",
						default=r'C:\Users\nvanderheijden\Documents\Regminer\regminer-topic-modelling\modeling\train_filtered.xlsx',
						type=str,
						required=False,
						help="Dir from where to parse the data.")
	parser.add_argument("--num_tags",
						default=100,
						type=int,
						help="Number of labels to use from the data (filters top N occurring)")
	parser.add_argument("--max_seq_len",
						default=100,
						type=int,
						help="Number of labels to use from the data (filters top N occurring)")
	parser.add_argument("--restructure_docs",
						action='store_false',
						help="Whether to restructure docs such that sentences are split/combined to evenly spread words over sequences.")
	parser.add_argument("--dataset_name",
						default='reuters',
						type=str,
						required=False,
						help="Name of the dataset.")
	parser.add_argument("--percentage_train",
						default=1.0,
						type=float,
						help="Percentage of train set to actually use for training when no train/dev/test split is given in data.")
	parser.add_argument("--percentage_dev",
						default=0.0,
						type=float,
						help="Percentage of train set to actually use for training when no train/dev/test split is given in data.")
	parser.add_argument("--write_data_dir",
						default='dataset\\regminer',
						type=str,
						required=False,
						help="Where to write the parsed data to.")
	parser.add_argument("--num_backtranslations",
						default=1,
						type=int,
						help="Number of times to backtranslate each document as means of data augmentation. Set to None for no backtranslation.")


	parser.add_argument("--train_path",
						type=str,
						required=True,
						help="The path from where the train dataset is to be retrieved.")
	parser.add_argument("--dev_path",
						required=True,
						type=str,
						help="The path from where the dev dataset is to be retrieved.")
	parser.add_argument("--test_path",
						type=str,
						required=False,
						help="The path from where the dev dataset is to be retrieved.")
	parser.add_argument("--create_wordvecs",
						action='store_true',
						help="Whether to create custom word vectors using FastText.")
	parser.add_argument("--word_vec_path",
						type=str,
						required=True,
						help="Folder where vector caches are stored.")
	parser.add_argument("--preload_word_to_idx",
						action='store_true',
						help="Whether to use an existing word to idx mapping.")
	parser.add_argument("--word_to_idx_path",
						type=str,
						required=True,
						help="The path from where the word mapping is to be retrieved.")
	parser.add_argument("--label_to_idx_path",
						default=os.path.join('dataset', 'reuters', 'label_to_idx.json'),
						type=str,
						required=True,
						help="The path from where the label mapping is to be retrieved.")
	parser.add_argument("--label_map_path",
						type=str,
						required=False,
						help="The path from where the mapping from label id to label description is loaded.")
	parser.add_argument("--min_freq_word",
						type=int,
						help="Minimum nr of occurrences before being assigned a word vector")

	#	OTHER ARGS
	parser.add_argument("--use_fasttext_baseline",
						action='store_true',
						help="Whether to use a FastText model for baseline purposes or not.")
	parser.add_argument("--autotune_time_fasttext",
						default=None,
						type=int,
						help="How many seconds to optimize fasttext hyperparams. Set to None to not perform autotuning")
	parser.add_argument("--fasttext_save_path",
						default=os.path.join('models', 'fasttext.model'),
						type=str,
						required=False,
						help="The path where to dump logging.")

	parser.add_argument("--log_path",
						default='log.txt',
						type=str,
						required=False,
						help="The path where to dump logging.")
	parser.add_argument("--tensorboard_dir",
						default='runs',
						type=str,
						required=False,
						help="The path where to dump logging.")
	parser.add_argument("--save_dir",
						default='models',
						type=str,
						required=False,
						help="Folder where to save models when training.")
	args = parser.parse_args()

	use_rnn = args.word_encoder == 'gru'
	train_path, dev_path, test_path = (args.train_path, args.dev_path, args.test_path)
	label_to_idx_path = args.label_to_idx_path
	word_vec_path = args.word_vec_path
	label_map = None
	ft_tmp_path = None
	unk = 'xxunk' if args.word_encoder == 'ulmfit' else '<UNK>'
	pad = 'xxpad' if args.word_encoder == 'ulmfit' else '<PAD>'
	# pr = cProfile.Profile()
	# pr.enable()

	###########################################################################
	# SANITY CHECKS
	###########################################################################

	assert (args.do_train or args.do_eval), "Either do_train and/or do_eval must be chosen"
	assert args.model_name.lower() in ['han', 'hgrulwan', 'hcapsnet', 'hcapsnetmultiheadatt'], "The model (--model_name) can be chosen from: HAN, HGRULWAN, HCapsNet, HCapsNetMultiHeadAtt."
	assert args.word_encoder.lower() in ['gru', 'transformer', 'ulmfit'], "The word encoder (--word_encoder) can only be set to GRU, Transformer and ULMFiT."
	assert args.sent_encoder.lower() in ['gru', 'transformer'], "The sentence encoder (--sent_encoder) can only be set to GRU or Transformer."

	if args.word_encoder.lower() == 'ulmfit':
		assert args.ulmfit_pretrained_path is not None, "if ULMFiT is chosen as word encoder its corresponding pretrained path (--ulmfit_pretrained_path) must be given."
		assert args.preload_word_to_idx, "If ULMFiT is chosen as word encoder --preload_word_to_idx must be set to True."

	if (args.preload_word_to_idx or args.pretrained_path):
		assert args.word_to_idx_path, "When either --preload_word_to_idx or --pretrained_path is given, its respectice --word_to_idx_path must also be given"

	if args.do_eval:
		assert args.test_path, "when --do_eval is set, --test_path must also be set"

	if args.preprocess_all:
		assert args.raw_data_dir, "When --preprocess_all is set, --raw_data_dir must also be set"
		assert args.write_data_dir, "When --preprocess_all is set, --write_data_dir must also be set"

		assert args.percentage_train + args.percentage_dev <= 1., "The percentage of data used for training and testing cannot be more than 100% together"

	###########################################################################
	# DATA PRE-PROCESSING
	###########################################################################
	if args.preload_word_to_idx:
		with open(args.word_to_idx_path, 'r') as f:
			# idx_to_label = json.load(f)
			word_to_idx = json.load(f)
			if args.word_encoder.lower() == 'ulmfit':
				word_to_idx = {v: i for i, v in enumerate(word_to_idx)}
	else:
		word_to_idx = None

	# TODO: refactor data reading --> only from df?
	if args.preprocess_all:
		if args.dataset_name.lower() == 'reuters':
			reuters_parse(args.write_data_dir, args.percentage_train, use_ulmfit=args.word_encoder.lower()=='ulmfit', restructure_doc=args.restructure_docs, max_seq_len=args.max_seq_len)
		elif args.dataset_name.lower() == 'eur-lex57k':
			label_to_idx_path, train_path, dev_path, test_path = \
				eur_lex_parse(args.raw_data_dir, args.write_data_dir, args.dataset_name, args.num_tags, args.num_backtranslations,
							  restructure_doc=args.restructure_docs, max_seq_len=args.max_seq_len)
		elif args.dataset_name.lower() == 'sheet':
			parse_sheet(args.raw_data_dir, args.write_data_dir, args.percentage_dev, 1.-args.percentage_train-args.percentage_dev, use_ulmfit=args.word_encoder.lower()=='ulmfit',
						restructure_doc=args.restructure_docs, max_seq_len=args.max_seq_len)
		else:
			raise AssertionError('Currently only Reuters, sheets and EUR-Lex57k are supported datasets for preprocessing.')

	#TODO: try considering only N last activations of LM to create doc encoding from
	#TODO: try gradual unfreezing when training
	if args.create_doc_encodings:
		encoder = ULMFiTEncoder(args.ulmfit_pretrained_path, len(word_to_idx), args.dropout_factor)
		encoder.eval()
		for p in [train_path, dev_path, test_path]:
			with open(p, 'rb') as f:
				docs = pickle.load(f)
			# set the encoding for all docs
			[doc.set_encoding(encoder.encode(torch.LongTensor([word_to_idx.get(tok, word_to_idx[unk]) for sen in doc.sentences for tok in sen]).unsqueeze(0)).detach().numpy()) for doc in tqdm.tqdm(docs)]

			with open(p, 'wb') as f:
				pickle.dump(docs, f)

	if args.create_wordvecs: # Create word vectors from train documents
		print('Creating word vectors')
		embeddings_from_docs(train_path, word_vec_path, word_vec_dim=args.embed_dim)

	###########################################################################
	# FastText Baseline and/or assisting model
	###########################################################################
	if args.use_fasttext_baseline: # Parse documents to train file for FastText

		ft_learner = FastTextLearner()
		ft_train_path = os.path.join('dataset', 'ft', 'train.txt')
		ft_dev_path = os.path.join('dataset', 'ft', 'dev.txt')
		ft_test_path = os.path.join('dataset', 'ft', 'test.txt')

		# Parse train
		doc_to_fasttext(train_path, ft_train_path)
		# Parse dev
		doc_to_fasttext(dev_path, ft_dev_path)
		# Parse test
		doc_to_fasttext(test_path, ft_test_path)

		ft_learner.train(ft_train_path, dev_path=ft_dev_path, save_path=args.fasttext_save_path, test_path=ft_test_path,
						 binary_classification=args.binary_class, optimize_time=args.autotune_time_fasttext, K=args.K)

		#TODO: optionally use FT learner to scope down routing process of capsule based networks.

	###########################################################################
	# DATA LOADING
	###########################################################################
	with open(label_to_idx_path, 'r') as f:
		# idx_to_label = json.load(f)
		label_to_idx = json.load(f)

	if args.label_map_path:
		with open(args.label_map_path, 'r') as f:
			# idx_to_label = json.load(f)
			label_map = json.load(f)


	# load docs into memory
	if args.do_train:
		with open(train_path, 'rb') as f:
			train_docs = pickle.load(f)

		with open(dev_path, 'rb') as f:
			dev_docs = pickle.load(f)



		# encoder.to(torch.device('cuda:0' if torch.cuda.is_available() else 'cpu'))
		# get dataloader
		train_dataset, word_to_idx, tag_counter_train = process_dataset(train_docs, word_to_idx=word_to_idx, label_to_idx=label_to_idx, min_freq_word=args.min_freq_word,
																		unk=unk, pad=pad)
		pos_weight = [v/len(train_dataset) for k,v in tag_counter_train.items()]
		# Fix for when not all labels are present in train set
		if len(pos_weight) != len(label_to_idx):
			pos_weight = None
		dataloader_train = get_data_loader(train_dataset, args.train_batch_size, True, use_rnn)

		# Save word_mapping
		with open(args.word_to_idx_path, 'w') as f:
			json.dump(word_to_idx, f)

		# Free some memory
		del train_dataset
		del train_docs


		dev_dataset, word_to_idx, tag_counter_dev = process_dataset(dev_docs, word_to_idx=word_to_idx, label_to_idx=label_to_idx, min_freq_word=None,
																	unk=unk, pad=pad)
		dataloader_dev = get_data_loader(dev_dataset, args.eval_batch_size, False, use_rnn)
		# Free some memory
		del dev_dataset
		del dev_docs
		gc.collect()

	###########################################################################
	# TRAIN MODEL
	###########################################################################
		# Init model
		if args.pretrained_path:
			TextClassifier = MultiLabelTextClassifier.load(args.pretrained_path)
		else:
			TextClassifier = MultiLabelTextClassifier(args.model_name, word_to_idx, label_to_idx, label_map, path_log = args.log_path,
													  save_dir=args.save_dir, tensorboard_dir=args.tensorboard_dir,
													  min_freq_word=args.min_freq_word, word_to_idx_path=args.word_to_idx_path,
													  B_train=args.train_batch_size, word_encoder = args.word_encoder,
													  B_eval=args.eval_batch_size, weight_decay=args.weight_decay, lr=args.learning_rate)

			TextClassifier.init_model(args.embed_dim, args.word_hidden, args.sent_hidden, args.dropout, args.word_vec_path, args.use_glove,
									  word_encoder=args.word_encoder, sent_encoder=args.sent_encoder, pos_weight=pos_weight,
									  dim_caps=args.dim_caps, num_caps=args.num_caps, num_compressed_caps=args.num_compressed_caps, nhead_doc=args.num_head_doc,
									  ulmfit_pretrained_path=args.ulmfit_pretrained_path, dropout_factor_ulmfit=args.dropout_factor)

		# Train
		TextClassifier.train(dataloader_train, dataloader_dev, pos_weight,
							 num_epochs=args.num_train_epochs, eval_every=args.eval_every)

	###########################################################################
	# EVAL MODEL
	###########################################################################
	if args.do_eval:
		if args.do_train: # Load best model obtained during training
			TextClassifier = MultiLabelTextClassifier.load(TextClassifier.pretrained_path)
		else: # Use model checkpoint
			TextClassifier = MultiLabelTextClassifier.load(args.pretrained_path)


		# Load test dataset
		with open(test_path, 'rb') as f:
			test_docs = pickle.load(f)

		# get dataloader
		test_dataset, word_to_idx, _ = process_dataset(test_docs, word_to_idx=word_to_idx,
																		label_to_idx=label_to_idx,
																		min_freq_word=None,
													   					unk=unk, pad = pad)

		dataloader_test = get_data_loader(test_dataset, args.eval_batch_size, True, use_rnn)

		TextClassifier.eval_dataset(dataloader_test)

