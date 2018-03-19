import numpy as np
import tensorflow as tf
from tensorflow.python.ops import array_ops


class Model(object):
    def __init__(
        self, 
        sequence_length, 
        num_classes, 
        vocab_size, 
        embedding_size, 
        hidden_size,
        filter_sizes, 
        num_filters, 
        l2_reg_lambda=0.0):

        # Placeholders for input, sequence length, output and dropout
        self.input_x = tf.placeholder(tf.int32, [None, sequence_length], name="input_x")
        self.seqlen = tf.placeholder(tf.int64, [None], name="seqlen")
        self.input_y = tf.placeholder(tf.float32, [None, num_classes], name="input_y")
        self.dropout_keep_prob = tf.placeholder(tf.float32, name="dropout_keep_prob")

        # Keeping track of l2 regularization loss (optional)
        l2_loss = tf.constant(0.0)


        # Embedding layer
        with tf.device('/cpu:0'), tf.name_scope("embedding"):
            self.W = tf.Variable(
                tf.random_uniform([vocab_size, embedding_size], -1.0, 1.0),
                trainable=True, 
                name="W")
            self.embedded_chars = tf.nn.embedding_lookup(self.W, self.input_x)
            #TODO: Embeddings process ignores commas etc. so seqlens might not be accurate for sentences with commas...     


        # Bidirectional LSTM layer
        with tf.name_scope("bidirectional-lstm"):
            lstm_fw_cell = tf.nn.rnn_cell.BasicLSTMCell(hidden_size, forget_bias=1.0)
            lstm_bw_cell = tf.nn.rnn_cell.BasicLSTMCell(hidden_size, forget_bias=1.0)

            # self.lstm_outputs, _, _ = tf.nn.bidirectional_dynamic_rnn(
            #     lstm_fw_cell, 
            #     lstm_bw_cell, 
            #     self.embedded_chars, 
            #     sequence_length=self.seqlen, 
            #     dtype=tf.float32)
            # lstm_outputs_fw, lstm_outputs_bw = tf.split(value=self.lstm_outputs, split_dim=2, num_split=2)
            # self.lstm_outputs = tf.add(lstm_outputs_fw, lstm_outputs_bw, name="lstm_outputs")

            with tf.variable_scope("lstm-output-fw"):
                self.lstm_outputs_fw, _ = tf.nn.dynamic_rnn(
                    lstm_fw_cell, 
                    self.embedded_chars, 
                    sequence_length=self.seqlen, 
                    dtype=tf.float32)

            with tf.variable_scope("lstm-output-bw"):
                self.embedded_chars_rev = array_ops.reverse_sequence(self.embedded_chars, seq_lengths=self.seqlen, seq_dim=1)
                tmp, _ = tf.nn.dynamic_rnn(
                    lstm_bw_cell, 
                    self.embedded_chars_rev, 
                    sequence_length=self.seqlen, 
                    dtype=tf.float32)
                self.lstm_outputs_bw = array_ops.reverse_sequence(tmp, seq_lengths=self.seqlen, seq_dim=1)

            # Concatenate outputs
            self.lstm_outputs = tf.add(self.lstm_outputs_fw, self.lstm_outputs_bw, name="lstm_outputs")
            
        self.lstm_outputs_expanded = tf.expand_dims(self.lstm_outputs, -1)


        # Convolution + maxpool layer for each filter size
        pooled_outputs = []
        for i, filter_size in enumerate(filter_sizes):
            with tf.name_scope("conv-maxpool-%s" % filter_size):
                # Convolution Layer
                filter_shape = [filter_size, hidden_size, 1, num_filters]
                W = tf.Variable(tf.truncated_normal(filter_shape, stddev=0.1), name="W")
                b = tf.Variable(tf.constant(0.1, shape=[num_filters]), name="b")
                
                conv = tf.nn.conv2d(
                    self.lstm_outputs_expanded, 
                    W,
                    strides=[1, 1, 1, 1], 
                    padding="VALID",
                    name="conv")
                                
                # Apply nonlinearity
                h = tf.nn.relu(tf.nn.bias_add(conv, b), name="relu")
                
                # Maxpooling over the outputs
                pooled = tf.nn.max_pool(
                    h, 
                    ksize=[1, sequence_length - filter_size + 1, 1, 1],
                    strides=[1, 1, 1, 1], 
                    padding='VALID',
                    name="pool")
                pooled_outputs.append(pooled)

        # Combine all the pooled features
        num_filters_total = num_filters * len(filter_sizes)
        self.h_pool = tf.concat(pooled_outputs, 3)
        self.h_pool_flat = tf.reshape(self.h_pool, [-1, num_filters_total])


        # Dropout layer
        with tf.name_scope("dropout"):
            self.h_drop = tf.nn.dropout(self.h_pool_flat, self.dropout_keep_prob)


        # Final (unnormalized) scores and predictions
        with tf.name_scope("output"):
            # Standard output weights initialization
            W = tf.get_variable(
                "W", 
                shape=[num_filters_total, num_classes], 
                initializer=tf.contrib.layers.xavier_initializer())
            b = tf.Variable(tf.constant(0.1, shape=[num_classes]), name="b")

            # # Initialized output weights to 0.0, might improve accuracy
            # W = tf.Variable(tf.constant(0.0, shape=[num_filters_total, num_classes]), name="W")
            # b = tf.Variable(tf.constant(0.0, shape=[num_classes]), name="b")
            
            l2_loss += tf.nn.l2_loss(W)
            l2_loss += tf.nn.l2_loss(b)
            
            self.scores = tf.nn.xw_plus_b(self.h_drop, W, b, name="scores")
            self.predictions = tf.argmax(self.scores, 1, name="predictions")

        # Calculate mean cross-entropy loss
        with tf.name_scope("loss"):
            losses = tf.nn.softmax_cross_entropy_with_logits(logits=self.scores, labels=self.input_y)
            self.loss = tf.reduce_mean(losses) + l2_reg_lambda * l2_loss

        # Accuracy
        with tf.name_scope("accuracy"):
            correct_predictions = tf.equal(self.predictions, tf.argmax(self.input_y, 1))
            self.accuracy = tf.reduce_mean(tf.cast(correct_predictions, "float"), name="accuracy")
