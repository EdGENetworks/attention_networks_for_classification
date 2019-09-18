import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from math import ceil

import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F

from torchnlp.encoders.text import stack_and_pad_tensors, pad_tensor


# ## Functions to accomplish attention

def batch_matmul_bias(seq, weight, bias, nonlinearity=''):
    s = None
    bias_dim = bias.size()
    for i in range(seq.size(0)):
        _s = torch.mm(seq[i], weight) 
        _s_bias = _s + bias.expand(bias_dim[0], _s.size()[0]).transpose(0,1)
        if(nonlinearity=='tanh'):
            _s_bias = torch.tanh(_s_bias)
        _s_bias = _s_bias.unsqueeze(0)
        if(s is None):
            s = _s_bias
        else:
            s = torch.cat((s,_s_bias),0)
    return s.squeeze()



def batch_matmul(seq, weight, nonlinearity=''):
    s = None
    for i in range(seq.size(0)):
        _s = torch.mm(seq[i], weight)
        if(nonlinearity=='tanh'):
            _s = torch.tanh(_s)
        _s = _s.unsqueeze(0)
        if(s is None):
            s = _s
        else:
            s = torch.cat((s,_s),0)
    return s.squeeze()



def attention_mul(rnn_outputs, att_weights):
    attn_vectors = None
    for i in range(rnn_outputs.size(0)):
        h_i = rnn_outputs[i]
        a_i = att_weights[i].unsqueeze(1).expand_as(h_i)
        h_i = a_i * h_i
        h_i = h_i.unsqueeze(0)
        if(attn_vectors is None):
            attn_vectors = h_i
        else:
            attn_vectors = torch.cat((attn_vectors,h_i),0)
    return torch.sum(attn_vectors, 0)


# ## Word attention model with bias

class AttentionWordRNN(nn.Module):
    
    
    def __init__(self, batch_size, num_tokens, embed_size, word_gru_hidden, bidirectional= True):        
        
        super(AttentionWordRNN, self).__init__()
        
        self.batch_size = batch_size
        self.num_tokens = num_tokens
        self.embed_size = embed_size
        self.word_gru_hidden = word_gru_hidden
        self.bidirectional = bidirectional
        
        self.lookup = nn.Embedding(num_tokens, embed_size)
        if bidirectional == True:
            self.word_gru = nn.GRU(embed_size, word_gru_hidden, bidirectional= True)
            self.weight_W_word = nn.Parameter(torch.Tensor(2* word_gru_hidden,2*word_gru_hidden))
            self.bias_word = nn.Parameter(torch.Tensor(2* word_gru_hidden,1))
            self.weight_proj_word = nn.Parameter(torch.Tensor(2*word_gru_hidden, 1))
        else:
            self.word_gru = nn.GRU(embed_size, word_gru_hidden, bidirectional= False)
            self.weight_W_word = nn.Parameter(torch.Tensor(word_gru_hidden, word_gru_hidden))
            self.bias_word = nn.Parameter(torch.Tensor(word_gru_hidden,1))
            self.weight_proj_word = nn.Parameter(torch.Tensor(word_gru_hidden, 1))
            
        self.softmax_word = nn.Softmax(dim=0)
        self.weight_W_word.data.uniform_(-0.1, 0.1)
        self.weight_proj_word.data.uniform_(-0.1,0.1)

        
        
    def forward(self, x):

        # embeddings
        y = self.lookup(x)
        if len(y.shape) == 2:
            print('HEUIOYHRIH@LFQBB')
            y = y.unsqueeze(1)
            # y = torch.unsqueeze(y, 1)
        # word level gru
        y, _ = self.word_gru(y)
#         print output_word.size()

        y = batch_matmul_bias(y, self.weight_W_word,self.bias_word, nonlinearity='tanh')
        word_attn = batch_matmul(y, self.weight_proj_word)
        word_attn_norm = self.softmax_word(word_attn)
        word_attn_vectors = attention_mul(y, word_attn_norm) #.transpose(1,0))
        return word_attn_vectors, word_attn_norm
    
    def init_hidden(self):
        if self.bidirectional == True:
            return Variable(torch.zeros(2, self.batch_size, self.word_gru_hidden))
        else:
            return Variable(torch.zeros(1, self.batch_size, self.word_gru_hidden))        


# ## Sentence Attention model with bias


class AttentionSentRNN(nn.Module):
    
    
    def __init__(self, batch_size, sent_gru_hidden, word_gru_hidden, n_classes, bidirectional= True):        
        
        super(AttentionSentRNN, self).__init__()
        
        self.batch_size = batch_size
        self.sent_gru_hidden = sent_gru_hidden
        self.n_classes = n_classes
        self.word_gru_hidden = word_gru_hidden
        self.bidirectional = bidirectional
        
        
        if bidirectional == True:
            self.sent_gru = nn.GRU(2 * word_gru_hidden, sent_gru_hidden, bidirectional= True)

            self.U = nn.Linear(2*sent_gru_hidden, n_classes)
            self.out = nn.Linear(2*sent_gru_hidden, n_classes) # nn.Parameter(torch.Tensor(2*sent_gru_hidden, n_classes))
            # self.weight_W_sent = nn.Parameter(torch.Tensor(2* sent_gru_hidden ,2* sent_gru_hidden))
            # self.bias_sent = nn.Parameter(torch.Tensor(2* sent_gru_hidden,1))
            # self.weight_proj_sent = nn.Parameter(torch.Tensor(2* sent_gru_hidden, 1))
            # self.final_linear = nn.Linear(2* sent_gru_hidden, n_classes)
        else:
            self.sent_gru = nn.GRU(word_gru_hidden, sent_gru_hidden, bidirectional= False)
            self.U = nn.Linear(sent_gru_hidden, n_classes)
            self.out = nn.Linear(sent_gru_hidden, n_classes)
            # self.weight_W_sent = nn.Parameter(torch.Tensor(sent_gru_hidden ,sent_gru_hidden))
            # self.bias_sent = nn.Parameter(torch.Tensor(sent_gru_hidden,1))
            # self.weight_proj_sent = nn.Parameter(torch.Tensor(sent_gru_hidden, 1))
            # self.final_linear = nn.Linear(sent_gru_hidden, n_classes)
        self.softmax_sent = nn.Softmax(dim=1) #TODO: set dim

        # self.softmax_label = nn.Softmax(dim=0)
        # # self.final_softmax = nn.Softmax()
        # self.weight_W_sent.data.uniform_(-0.1, 0.1)
        # self.weight_proj_sent.data.uniform_(-0.1,0.1)
        
        
    def forward(self, word_attention_vectors):

        B, N, d_c = word_attention_vectors.size()
        output_sent, _ = self.sent_gru(word_attention_vectors)

        H = output_sent.permute(1,0,2)
        # Get labelwise attention scores per document
        # A: [B, N, L] -> softmax-normalized scores per sentence per label
        # A1 = H @ self.U
        A1 = self.U(H)
        A = self.softmax_sent(A1)
        # Get labelwise representations of doc
        test = torch.repeat_interleave(A, d_c, dim=2)
        H_expanded = H.repeat(1,1,self.n_classes)

        V = (test * H_expanded).view(B, N, self.n_classes, d_c).sum(dim=1)
        # V = (H.contiguous().view(-1) @ test.contiguous().view(-1, self.n_classes))
        #TODO: labelwise attention can be done more efficiently
        # Get final predictions
        y = self.out(V)

        # Take diagonal over predictions per label to cut out mismatches in d_l beta_j for l != j (binary classification per label representation of document)

        y = y.diagonal(dim1=1, dim2=2)
        return y, A
        # sent_squish = batch_matmul_bias(output_sent, self.weight_W_sent,self.bias_sent, nonlinearity='tanh')
        # sent_attn = batch_matmul(sent_squish, self.weight_proj_sent)
        # sent_attn_norm = self.softmax_sent(sent_attn.transpose(1,0))
        # sent_attn_vectors = attention_mul(output_sent, sent_attn_norm.transpose(1,0))
        # # final classifier
        # final_map = self.final_linear(sent_attn_vectors.squeeze(0))
        # return F.log_softmax(final_map), state_sent, sent_attn_norm
    
    def init_hidden(self):
        if self.bidirectional == True:
            return Variable(torch.zeros(2, self.batch_size, self.sent_gru_hidden))
        else:
            return Variable(torch.zeros(1, self.batch_size, self.sent_gru_hidden))


class HAN(nn.Module):

        def __init__(self, batch_size, num_tokens, embed_size, sent_gru_hidden, word_gru_hidden, n_classes, bidirectional= True):
            super(HAN, self).__init__()

            self.batch_size = batch_size
            self.sent_gru_hidden = sent_gru_hidden
            self.n_classes = n_classes
            self.word_gru_hidden = word_gru_hidden
            self.bidirectional = bidirectional

            self.sent_encoder = AttentionWordRNN(batch_size, num_tokens, embed_size, word_gru_hidden, bidirectional)
            self.doc_encoder = AttentionSentRNN(batch_size, sent_gru_hidden, word_gru_hidden, n_classes, bidirectional)

        def set_embedding(self, embed_table):
            self.sent_encoder.lookup.load_state_dict({'weight': torch.tensor(embed_table)})

        def forward(self, sents, sents_len, doc_lens):

            # Account for batch size
            sen_len, B = sents.size()
            b = self.batch_size

            # state_word = self.sent_encoder.init_hidden().cuda()
            sen_encodings = None
            for i in range(ceil(B / b)):
                word_attention , _ = self.sent_encoder(sents[:,i*b:(i+1)*b])
                if (sen_encodings is None):
                    sen_encodings = word_attention
                else:
                    sen_encodings = torch.cat((sen_encodings, word_attention), 0)


            # sen_encodings = [self.sent_encoder(sents[:,i*b:(i+1)*b])[0] for i in range(ceil(B / b))]
            # sen_encodings = torch.cat(s) #TODO: batchnorm
            # split sen encodings per doc
            sen_encodings = sen_encodings.split(split_size=doc_lens)
            # stack and pad
            sen_encodings, _ = stack_and_pad_tensors(sen_encodings) #

            # get predictions
            y_pred = self.doc_encoder(sen_encodings)
            return y_pred