import torch
import torch.nn as nn
from torchnlp.encoders.text import stack_and_pad_tensors, pad_tensor
# ## Word attention model with bias
from layers import *
import fasttext
transpose = (lambda b: b.t_().squeeze(0).contiguous())


class FastTextLearner:

    def __init__(self):
        self.model = None

    def train(self, train_path, dev_path=None, test_path=None, save_path = None, optimize_time=None, binary_classification=True,
              lr=0.2, epoch=100,embed_size=300, K=5):
        # optimize_time given in seconds

        # train model
        if not optimize_time:
            self.model = fasttext.train_supervised(train_path, loss='hs' if binary_classification else 'ova', lr=lr, epoch=epoch, dim=embed_size)
        else: # optimize params..
            assert dev_path, "When FastText is optimized, a development set must also be given"
            self.model = fasttext.train_supervised(train_path, autotune_validation_file=dev_path, autotune_duration=optimize_time, loss='hs' if binary_classification else 'ova')
            fasttext.train_supervised()

        if test_path:
            N, p_k, r_k = self.model.test(test_path, K)
            print("FastText model attained P@{0}: {1:0.3f}, R@{0}: {2:0.3f}, F1@{0}: {3:0.3f}".format(K, p_k, r_k, (2*p_k*r_k)/(r_k+p_k)))

        # save if necessary
        if save_path:
            self.model.save_model(save_path) #TODO: quantization?



class HAN(nn.Module):

    def __init__(self, num_tokens, embed_size, word_hidden, sent_hidden, num_classes, bidirectional=True, dropout=0.1, word_encoder='GRU', sent_encoder='GRU',
                 num_layers_word = 1, num_layers_sen = 1, nhead_word = 4, nhead_sen = 4, **kwargs):
        super(HAN, self).__init__()

        # self.batch_size = batch_size
        self.sent_gru_hidden = sent_hidden
        self.n_classes = num_classes
        self.word_hidden = word_hidden
        self.bidirectional = bidirectional
        self.word_contextualizer = word_encoder
        self.sent_contextualizer = sent_encoder

        word_out = 2 * word_hidden if (bidirectional and word_encoder.lower() =='gru')  else word_hidden
        sent_out = 2 * sent_hidden if (bidirectional and sent_encoder.lower() =='gru')  else sent_hidden

        self.sent_encoder = AttentionWordEncoder(word_encoder, num_tokens, embed_size, word_hidden,
                                                 bidirectional=bidirectional,
                                                 num_layers=num_layers_word, nhead=nhead_word
                                                 )
        self.doc_encoder = AttentionSentEncoder(sent_encoder, sent_hidden, word_out,
                                                bidirectional=bidirectional,
                                                num_layers=num_layers_sen, nhead=nhead_sen)

        self.out = nn.Linear(sent_out, num_classes)
        self.bn = nn.BatchNorm1d(sent_out)
        self.drop = nn.Dropout(dropout)

    def set_embedding(self, embed_table):
        self.sent_encoder.lookup.load_state_dict({'weight': torch.tensor(embed_table)})


    def forward(self, sents, sents_len, doc_lens):

        sen_encodings, word_attn_weight = self.sent_encoder(sents)

        # if self.word_contextualizer != self.sent_contextualizer:
        #     sen_encodings = sen_encodings.permute(1, 0, 2)

        sen_encodings = sen_encodings.split(split_size=doc_lens)
        # stack and pad
        sen_encodings, _ = stack_and_pad_tensors(sen_encodings)  #
        # get predictions
        doc_encoding, sent_attn_weight = self.doc_encoder(sen_encodings)

        doc_encoding = self.drop(self.bn(doc_encoding))

        y_pred = self.out(doc_encoding)

        return y_pred, word_attn_weight, sent_attn_weight #TODO: split out forward and predict fn for attn_weights?


class HGRULWAN(nn.Module):

        def __init__(self, num_tokens, embed_size, sent_gru_hidden, word_gru_hidden, num_classes, bidirectional= True, dropout=0.1, **kwargs):
            super(HGRULWAN, self).__init__()

            # self.batch_size = batch_size
            self.sent_gru_hidden = sent_gru_hidden
            self.num_classes = num_classes
            self.word_gru_hidden = word_gru_hidden
            self.bidirectional = bidirectional

            self.sent_encoder = AttentionWordEncoder('gru', num_tokens, embed_size, word_gru_hidden, bidirectional, dropout=dropout)
            self.doc_encoder = GRUMultiHeadAtt(sent_gru_hidden, word_gru_hidden, nhead_doc=num_classes,
                                               bidirectional=bidirectional, dropout=dropout, aggregate_output=True)

        def set_embedding(self, embed_table):
            self.sent_encoder.lookup.load_state_dict({'weight': torch.tensor(embed_table)})

        def forward(self, sents, sents_len, doc_lens):

            sen_encodings, word_attn_weight = self.sent_encoder(sents)

            sen_encodings = sen_encodings.split(split_size=doc_lens)
            # stack and pad
            sen_encodings, _ = stack_and_pad_tensors(sen_encodings) #
            # get predictions
            y_pred, sent_attn_weight = self.doc_encoder(sen_encodings)
            return y_pred, word_attn_weight, sent_attn_weight


class HCapsNet(nn.Module):
    def __init__(self, num_tokens, embed_size, word_hidden, sent_hidden, num_classes, bidirectional=True, dropout=0.1, word_encoder='GRU', sent_encoder='GRU',
                 num_layers_word = 1, num_layers_sen = 1, nhead_word = 4, nhead_sen = 4, dim_caps=16, num_caps = 25, num_compressed_caps = 100, **kwargs):
        super(HCapsNet, self).__init__()

        # self.batch_size = batch_size
        self.sent_gru_hidden = sent_hidden
        self.n_classes = num_classes
        self.word_hidden = word_hidden
        self.bidirectional = bidirectional
        self.word_contextualizer = word_encoder
        self.sent_contextualizer = sent_encoder

        word_out = 2 * word_hidden if (bidirectional and word_encoder.lower() =='gru')  else word_hidden
        sent_out = 2 * sent_hidden if (bidirectional and sent_encoder.lower() =='gru')  else sent_hidden

        self.sent_encoder = AttentionWordEncoder(word_encoder, num_tokens, embed_size, word_hidden,
                                                 bidirectional=bidirectional,
                                                 num_layers=num_layers_word, nhead=nhead_word
                                                 )
        self.doc_encoder = AttentionSentEncoder(sent_encoder, sent_hidden, word_out,
                                                bidirectional=bidirectional,
                                                num_layers=num_layers_sen, nhead=nhead_sen)

        self.caps_classifier = CapsNet_Text(sent_out, 1, num_classes, dim_caps=dim_caps, num_caps=num_caps, num_compressed_caps=num_compressed_caps)
        # self.out = nn.Linear(sent_out, num_classes)
        self.bn = nn.BatchNorm1d(sent_out)
        self.drop = nn.Dropout(dropout)

    def set_embedding(self, embed_table):
        self.sent_encoder.lookup.load_state_dict({'weight': torch.tensor(embed_table)})


    def forward(self, sents, sents_len, doc_lens):

        sen_encodings, word_attn_weight = self.sent_encoder(sents)

        # if self.word_contextualizer != self.sent_contextualizer:
        #     sen_encodings = sen_encodings.permute(1, 0, 2)

        sen_encodings = sen_encodings.split(split_size=doc_lens)
        # stack and pad
        sen_encodings, _ = stack_and_pad_tensors(sen_encodings)  #
        # get predictions
        doc_encoding, sent_attn_weight = self.doc_encoder(sen_encodings)

        doc_encoding = self.bn(doc_encoding).unsqueeze(1) #self.drop()

        poses, activations = self.caps_classifier(doc_encoding)
        activations = activations.squeeze(2)

        # TEMP: reconstuction
        rec_los = self.caps_classifier.reconstruction_loss(doc_encoding.squeeze(1), poses)

        return activations, word_attn_weight, sent_attn_weight, rec_los


class HCapsNetMultiHeadAtt(nn.Module):
    def __init__(self, num_tokens, embed_size, word_hidden, sent_hidden, num_classes, bidirectional=True, dropout=0.1, word_encoder='GRU', sent_encoder='GRU',
                 num_layers_word = 1, num_layers_sen = 1, nhead_word = 4, nhead_sen = 4, dim_caps=16, num_caps = 25, num_compressed_caps = 100, nhead_doc = 25, **kwargs):
        super(HCapsNetMultiHeadAtt, self).__init__()

        # self.batch_size = batch_size
        self.sent_gru_hidden = sent_hidden
        self.n_classes = num_classes
        self.word_hidden = word_hidden
        self.bidirectional = bidirectional
        self.word_contextualizer = word_encoder
        self.sent_contextualizer = sent_encoder

        word_out = 2 * word_hidden if (bidirectional and word_encoder.lower() =='gru')  else word_hidden
        sent_out = 2 * sent_hidden if (bidirectional and sent_encoder.lower() =='gru')  else sent_hidden

        self.sent_encoder = AttentionWordEncoder(word_encoder, num_tokens, embed_size, word_hidden,
                                                 bidirectional=bidirectional,
                                                 num_layers=num_layers_word, nhead=nhead_word
                                                 )
        self.doc_encoder = GRUMultiHeadAtt(sent_hidden, word_out, nhead_doc=nhead_doc,
                                           bidirectional=bidirectional, dropout=dropout, aggregate_output=False)

        self.caps_classifier = CapsNet_Text(sent_out, nhead_doc, num_classes,
                                            dim_caps=dim_caps, num_caps=num_caps, num_compressed_caps=num_compressed_caps)
        # self.out = nn.Linear(sent_out, num_classes)
        self.bn = nn.BatchNorm1d(sent_out)
        self.drop = nn.Dropout(dropout)

    def set_embedding(self, embed_table):
        self.sent_encoder.lookup.load_state_dict({'weight': torch.tensor(embed_table)})


    def forward(self, sents, sents_len, doc_lens):

        sen_encodings, word_attn_weight = self.sent_encoder(sents)

        # if self.word_contextualizer != self.sent_contextualizer:
        #     sen_encodings = sen_encodings.permute(1, 0, 2)

        sen_encodings = sen_encodings.split(split_size=doc_lens)
        # stack and pad
        sen_encodings, _ = stack_and_pad_tensors(sen_encodings)  #
        # get predictions
        doc_encoding, sent_attn_weight = self.doc_encoder(sen_encodings)

        doc_encoding = self.drop(self.bn(doc_encoding.permute(0,2,1))).permute(0,2,1)
        # doc_encoding = self.drop(self.bn(doc_encoding))

        poses, activations = self.caps_classifier(doc_encoding)
        activations = activations.squeeze(2)



        return activations, word_attn_weight, sent_attn_weight