# python train_vgg.py -t kbeast

from __future__ import print_function

try:
    import matplotlib
    matplotlib.use('Agg')
except ImportError:
    pass

import pdb
import argparse
import pickle
import json
import numpy as np
import chainer
import chainer.functions as F
import chainer.links as L
from chainer import training
from chainer.training import extensions
from chainer import cuda
from chainer.dataset import dataset_mixin
from model import MLP, VGG, SVM

from prep_data import JsonToVec, InitVec, prep_windowed_datasets
from confusionmatrix import ConfusionMatrix


class KernelMemoryDataset(chainer.dataset.dataset_mixin.DatasetMixin):
    def __init__(self, X, Y):
        Y = np.array(Y, dtype=np.int32)
        self.data = [[xi, Y[t]] for t, xi in enumerate(X)]

    def __len__(self):
        return len(self.data)

    def get_example(self, i):
        vector = self.data[i][0]
        label = self.data[i][1]
        return (vector, label)

def load_memory_datasets(train_dataset_name_labels, test_dataset_name_labels):
    # train_dataset_name_labels : list of (filename, label)
    # test_dataset_name_label : (filename, true label)
    # --> TupleDataset
    train_x, train_y = InitVec(train_dataset_name_labels)
    train_dataset = KernelMemoryDataset(train_x, train_y)

    test_x, test_y = InitVec(test_dataset_name_labels)
    test_dataset = KernelMemoryDataset(test_x, test_y)

    return train_dataset, test_dataset

def main():
    parser = argparse.ArgumentParser(description='Memlearn Chainer ver')
    parser.add_argument('--batchsize', '-b', type=int, default=100,
                        help='Number of images in each mini-batch')
    parser.add_argument('--epoch', '-e', type=int, default=20,
                        help='Number of sweeps over the dataset to train')
    parser.add_argument('--frequency', '-f', type=int, default=-1,
                        help='Frequency of taking a snapshot')
    parser.add_argument('--gpu', '-g', type=int, default=-1,
                        help='GPU ID (negative value indicates CPU)')
    parser.add_argument('--out', '-o', default='result',
                        help='Directory to output the result')
    parser.add_argument('--resume', '-r', default='',
                        help='Resume the training from snapshot')
    parser.add_argument('--train', '-i', nargs='*',
                        help='Train data (all except test by default)')
    parser.add_argument('--test', '-t', nargs='*',
                        help='Test data (you have to specify at least one')
    parser.add_argument('--sliceb', '-s', type=int, default=1,
                        help='Time slice block')    
    parser.add_argument('--list_dataset', action='store_true')
    parser.add_argument('--dataset', default="/data/data_filtered.pickle")

    args = parser.parse_args()

    if args.list_dataset:
        with open(args.dataset, 'rb') as fp:
            dataset = pickle.load(fp)
            print('\n'.join(['{} {}'.format(n, l) for n, l in dataset]))
            raise SystemExit

    if not args.test:
        raise SystemExit("you have to specify at least one test, see --list_dataset for available datasets")

    print('GPU: {}'.format(args.gpu))
    print('# Minibatch-size: {}'.format(args.batchsize))
    print('# epoch: {}'.format(args.epoch))
    print('')


    # Set up a neural network to train
    # Classifier reports softmax cross entropy loss and accuracy at every
    # iteration, which will be used by the PrintReport extension below.
    model = L.Classifier(VGG(2))
    #model = L.Classifier(SVM())
    if args.gpu >= 0:
        # Make a specified GPU current
        chainer.cuda.get_device_from_id(args.gpu).use()
        model.to_gpu()  # Copy the model to the GPU

    # Setup an optimizer
    optimizer = chainer.optimizers.Adam()
    optimizer.setup(model)

    # Load the MEMORY dataset
    train, test = prep_windowed_datasets(args.dataset, args.test, args.train, slice_merge=args.sliceb)
    train_iter = chainer.iterators.SerialIterator(train, args.batchsize)
    test_iter = chainer.iterators.SerialIterator(test, args.batchsize,
                                                 repeat=False, shuffle=False)

    # Set up a trainer
    updater = training.StandardUpdater(train_iter, optimizer, device=args.gpu)
    trainer = training.Trainer(updater, (args.epoch, 'epoch'), out=args.out)

    # Evaluate the model with the test dataset for each epoch
    #trainer.extend(extensions.Evaluator(test_iter, model, device=args.gpu))
    trainer.extend(ConfusionMatrix(test_iter, model, device=args.gpu))

    # Dump a computational graph from 'loss' variable at the first iteration
    # The "main" refers to the target link of the "main" optimizer.
    trainer.extend(extensions.dump_graph('main/loss'))

    # Take a snapshot for each specified epoch
    frequency = args.epoch if args.frequency == -1 else max(1, args.frequency)
    trainer.extend(extensions.snapshot(), trigger=(frequency, 'epoch'))

    # Write a log of evaluation statistics for each epoch
    trainer.extend(extensions.LogReport())

    # Save two plot images to the result dir
    if extensions.PlotReport.available():
        trainer.extend(
            extensions.PlotReport(['main/loss', 'validation/main/loss'],
                                  'epoch', file_name='loss.png'))
        trainer.extend(
            extensions.PlotReport(
                ['main/accuracy', 'validation/main/accuracy'],
                'epoch', file_name='accuracy.png'))

    # Print selected entries of the log to stdout
    # Here "main" refers to the target link of the "main" optimizer again, and
    # "validation" refers to the default name of the Evaluator extension.
    # Entries other than 'epoch' are reported by the Classifier link, called by
    # either the updater or the evaluator.
    trainer.extend(extensions.PrintReport(
        ['epoch', 'main/loss', 'validation/main/loss',
         'main/accuracy', 'validation/main/accuracy', 'elapsed_time']))

    # Print a progress bar to stdout
    trainer.extend(extensions.ProgressBar())

    if args.resume:
        # Resume from a snapshot
        chainer.serializers.load_npz(args.resume, trainer)

    # Run the training
    trainer.run()


if __name__ == '__main__':
    main()
