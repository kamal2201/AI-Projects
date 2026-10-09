import torch
import torch.nn as nn
import math

class InputEmbeddings(nn.Module):
    
    def __init__(self, d_model: int, vocab_size: int):
        super().__init__()
        self.d_model = d_model
        self.vocab_size = vocab_size
        self.embedding = nn.Embedding(vocab_size, d_model)
        
    def forward(self, x):
        return self.embedding(x) * math.sqrt(self.d_model)
    
class PositionalEncoding(nn.Module):
    
    def __init__(self, d_model: int, seq_length: int, dropout: float) -> None:
        super().__init__()
        self.d_model = d_model
        self.seq_length = seq_length
        self.dropout = nn.Dropout(dropout)
        
        # Create a matrix of shape (seq_lenght, d_model) to hold the positional encodings
        pe = torch.zeros(seq_length, d_model)
        # Create a vector of shape (seq_length, 1)
        position = torch.arange(0, seq_length, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        # Apply the sine function to even indices in the array; 2i
        pe[:, 0::2] = torch.sin(position * div_term)
        # Apply the cosine function to odd indices in the array; 2i+1
        pe[:, 1::2] = torch.cos(position * div_term)
        
        pe = pe.unsqueeze(0) # Shape (1, seq_length, d_model)
         
        self.register_buffer('pe', pe)
        
    def forward(self, x):
        x = x + (self.pe[:, :x.shape[1], :]).requires_grad_(False)
        return self.dropout(x) 
        
class LayerNormalization(nn.Module):
    
    def __init__(self, eps: float = 10**-6):
        super().__init__()
        self.eps = eps
        self.alpha = nn.Parameter(torch.ones(1)) # Multiplier for scaling the normalized output
        self.bias = nn.Parameter(torch.zeros(1)) # Additive bias for shifting the normalized output
        
    def forward(self, x):
        mean = x.mean(dim = -1, keepdim = True)
        std = x.std(dim = -1, keepdim = True)
        return self.alpha * (x - mean) / (std + self.eps) + self.bias
    
class FeedForwardBlock(nn.Module):
    
    def __init__(self, d_model: int, d_ff: int, dropout: float):
        super().__init__()
        self.linear1 = nn.Linear(d_model, d_ff) # W1 and b1 are the weights and bias for the first linear layer
        self.dropout = nn.Dropout(dropout)
        self.linear2 = nn.Linear(d_ff, d_model) # W2 and b2 are the weights and bias for the second linear layer
        
    def forward(self, x):
        # (batch_size, seq_length, d_model) -> (batch_size, seq_length, d_ff) -> (batch_size, seq_length, d_model)
        x = self.linear1(x)
        x = torch.relu(x)
        x = self.dropout(x)
        x = self.linear2(x)
        return x
    
class MultiHeadAttention(nn.Module):
    
    def __init__(self, d_model: int, h: int, dropout: float) -> None:
        super().__init__()
        self.d_model = d_model
        self.h = h
        assert d_model % h == 0, "d_model must be divisible by h"
        
        self.d_k = d_model // h
        
        self.w_q = nn.Linear(d_model, d_model)
        self.w_k = nn.Linear(d_model, d_model)
        self.w_v = nn.Linear(d_model, d_model)
        
        self.w_o = nn.Linear(d_model, d_model)
        
        self.dropout = nn.Dropout(dropout)
        
    @staticmethod
    def attention(self, query, key, value, mask = None, dropout = None):
        d_k = query.size(-1)
        
        # (batch_size, h, seq_length, d_k) @ (batch_size, h, d_k, seq_length) -> (batch_size, h, seq_length, seq_length)
        attention_scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(d_k) # (batch_size, h, seq_length, seq_length)
        if mask is not None:
            attention_scores = attention_scores.masked_fill(mask == 0, -1e9)
            
        attention_scores = torch.softmax(attention_scores, dim = -1) # (batch_size, h, seq_length, seq_length)
        
        if dropout is not None:
            attention_scores = dropout(attention_scores)
            
        return (attention_scores @ value, attention_scores) # (batch_size, h, seq_length, d_k), (batch_size, h, seq_length, seq_length)
        
    def forward(self, q, k, v, mask = None):
        query = self.w_q(q) # (batch_size, seq_length, d_model)
        key = self.w_k(k)   # (batch_size, seq_length, d_model)
        value = self.w_v(v) # (batch_size, seq_length, d_model)
        
        # (batch_size, seq_length, d_model) -> (batch_soze, seq_length, h, d_k) -> apply transpose -> (batch_size, h, seq_length, d_k)
        query = query.view(query.shape[0], query.shape[1], self.h, self.d_k).transpose(1, 2) # (batch_size, h, seq_length, d_k)
        key = key.view(key.shape[0], key.shape[1], self.h, self.d_k).transpose(1, 2) # (batch_size, h, seq_length, d_k)
        value = value.view(value.shape[0], value.shape[1], self.h, self.d_k).transpose(1, 2) # (batch_size, h, seq_length, d_k)
        
        x, self.attention_scores = MultiHeadAttention.attention(self, query, key, value, mask, self.dropout) # (batch_size, h, seq_length, d_k)

        x = x.transpose(1, 2).contiguous().view(x.shape[0], x.shape[2], self.d_model) # (batch_size, seq_length, d_model)
        
        return self.w_o(x) # (batch_size, seq_length, d_model)
    
class ResidualConnection(nn.Module):
    
    def __init__(self, dropout: float) -> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.norm = LayerNormalization()
        
    def forward(self, x, sublayer):
        return x + self.dropout(sublayer(self.norm(x)))
    
class EncoderBlock(nn.Module):
    
    def __init__(self, self_attention_block: MultiHeadAttention, feed_forward_block: FeedForward, dropout: float) -> None:
        super().__init__()
        self.self_attention_block = self_attention_block
        self.feed_forward_block = feed_forward_block
        self.residual_connections = nn.ModuleList([ResidualConnection(dropout) for _ in range(2)])
        
    def forward(self, x, src_mask = None):
        x = self.residual_connections[0](x, lambda x: self.self_attention_block(x, x, x, src_mask))
        x = self.residual_connections[1](x, self.feed_forward_block)
        return x
    
class Encoder(nn.Module):
    
    def __init__(self, layers: nn.ModuleList) -> None:
        super().__init__()
        self.layers = layers
        self.norm = LayerNormalization()
        
    def forward(self, x, mask = None):
        for layer in self.layers:
            x = layer(x, mask)
        return self.norm(x)
    