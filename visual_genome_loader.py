
import os
import json
import torch
import errno
import numpy as np
import os.path as osp
from PIL import Image
import torch.utils.data as data
import visual_genome.local as vg


class Dictionary(object):
    def __init__(self):
        self.word2idx = {}
        self.idx2word = []

    def add_word(self, word):
        if word not in self.word2idx:
            self.idx2word.append(word)
            self.word2idx[word] = len(self.idx2word) - 1
        return self.word2idx[word]

    def __len__(self):
        return len(self.idx2word)


class Corpus(object):
    def __init__(self):
        self.dictionary = Dictionary()

    def add_to_corpus(self, line):
        """Tokenizes a text line."""
        # Add words to the dictionary
        words = line.split() + ['<eos>']
        # tokens = len(words)
        for word in words:
            self.dictionary.add_word(word)

    def tokenize(self, line):
        # Tokenize line contents
        words = line.split() + ['<eos>']
        tokens = len(words)
        ids = torch.LongTensor(tokens)
        token = 0
        for word in words:
            if word not in self.dictionary.word2idx:
                word = '<unk>'
            ids[token] = self.dictionary.word2idx[word]
            token += 1

        return ids


class VisualGenomeLoader(data.Dataset):
    data_path = 'data'
    processed_folder = 'processed'
    corpus_file = 'corpus.pt'
    train_text_file = 'train.txt'
    val_text_file = 'val.txt'
    test_text_file = 'test.txt'
    region_train_file = 'region_train.pt'
    region_val_file = 'region_val.pt'
    region_test_file = 'region_test.pt'

    def __init__(self, root, transform=None, train=True, test=False,
                 top=100):
        self.root = root
        self.transform = transform
        self.top_objects = top
        self.top_folder = 'top_{0}'.format(top)

        if not osp.exists(self.root):
            raise RuntimeError('Dataset not found ' +
                               'please download it from: ' +
                               'http://visualgenome.org/api/v0/api_home.html')

        if not self.__check_exists():
            self.process_dataset()

        if train:
            train_file = osp.join(self.root, self.top_folder,
                                  self.region_train_file)
            with open(train_file, 'rb') as f:
                self.regions = torch.load(f)
        elif test:
            test_file = osp.join(self.root, self.top_folder,
                                 self.region_test_file)
            with open(test_file, 'rb') as f:
                self.regions = torch.load(f)
        else:
            val_file = osp.join(self.root, self.top_folder,
                                self.region_val_file)
            with open(val_file, 'rb') as f:
                self.regions = torch.load(f)

        corpus_file = osp.join(self.data_path, self.processed_folder,
                               self.corpus_file)
        with open(corpus_file, 'rb') as f:
            self.corpus = torch.load(f)

    def __check_exists(self):
        path = osp.join(self.root, self.top_folder)
        return osp.exists(path)

    def process_dataset(self):
        try:
            os.makedirs(osp.join(self.data_path, self.top_folder))
            os.makedirs(osp.join(self.data_path, self.processed_folder))
        except OSError as e:
            if e.errno == errno.EEXIST:
                pass
            else:
                raise

        print("Generating top images set...")
        img_top_ids = self.get_top_images()

        print("Processing region descriptions...")
        region_descriptions_full = vg.get_all_region_descriptions(
            data_dir=self.root)

        region_descriptions = []
        for region in region_descriptions_full:
            region_descriptions += region

        del region_descriptions_full

        corpus_path = osp.join(self.data_path, self.processed_folder,
                               self.corpus_file)

        if not osp.exists(corpus_path):
            print("Generating text corpus...")
            corpus = Corpus()
            for i, region in enumerate(region_descriptions):
                print("Processing region: {0}".format(i))
                corpus.add_to_corpus(region.phrase)

            corpus.dictionary.add_word('<unk>')
            print("Saving corpus to file...")
            with open(corpus_path, 'wb') as f:
                torch.save(corpus, f)

        print("Selecting region descriptions from top images...")
        regions = []
        for i, region in enumerate(region_descriptions):
            print("Processing region: {0}".format(i))
            if region.image.id in img_top_ids:
                regions.append(region)

        print("Splitting region descriptions...")
        train_prop = np.ceil(len(regions) * 0.6)
        val_train_prop = np.ceil(len(regions) * 0.15)

        regions = np.array(regions)
        np.random.shuffle(regions)

        train_regions = regions[:train_prop].tolist()
        val_regions = regions[train_prop:train_prop + val_train_prop].tolist()
        test_regions = regions[train_prop + val_train_prop:].tolist()

        print("Saving train text corpus...")
        train_text_path = osp.join(self.root, self.top_folder,
                                   self.train_text_file)
        with open(train_text_path, 'w') as f:
            for region in train_regions:
                f.write(region.phrase + '\n')

        print("Saving validation text corpus...")
        val_text_path = osp.join(self.root, self.top_folder,
                                 self.val_text_file)
        with open(val_text_path, 'w') as f:
            for region in val_regions:
                f.write(region.phrase + '\n')

        print("Saving test text corpus...")
        test_text_path = osp.join(self.root, self.top_folder,
                                  self.test_text_file)
        with open(test_text_path, 'w') as f:
            for region in test_regions:
                f.write(region.phrase + '\n')

        print("Saving training regions...")
        train_file = osp.join(self.root, self.top_folder,
                              self.region_train_file)
        with open(train_file, 'wb') as f:
            torch.save(train_regions, f)

        print("Saving validation regions...")
        val_file = osp.join(self.root, self.top_folder,
                            self.region_val_file)
        with open(val_file, 'wb') as f:
            torch.save(val_regions, f)

        print("Saving testing regions...")
        test_file = osp.join(self.root, self.top_folder,
                             self.region_test_file)
        with open(test_file, 'wb') as f:
            torch.save(test_regions, f)

        print("Done!")

    def get_top_images(self):
        obj_file_path = osp.join(self.root, 'objects.json')
        objects = json.load(open(obj_file_path, 'r'))

        total_objects = {}
        for img_obj in objects:
            for obj in img_obj['objects']:
                for name in obj['names']:
                    if name not in total_objects:
                        total_objects[name] = 0
                    total_objects[name] += 1

        sorted_objs = sorted(total_objects.keys(),
                             key=lambda k: total_objects[k],
                             reverse=True)
        sorted_objs = sorted_objs[0:self.top_objects]

        valid_img_ids = []
        for img_obj in objects:
            found = False
            for obj in img_obj['objects']:
                for name in obj['names']:
                    if name in sorted_objs:
                        valid_img_ids.append[img_obj['image_id']]
                        found = True
                        break
                if found:
                    break

        return valid_img_ids

    def __len__(self):
        return len(self.regions)

    def __getitem__(self, idx):
        region = self.regions[idx]
        image_info = region.image

        # if image_info.id not in self.cache:
        image_path = image_info.url.split('/')[-2:]
        image_path = osp.join(self.root, *image_path)
        img = Image.open(image_path).convert('RGB')
        # self.cache[image_info.id] = img

        # img = self.cache[image_info.id]
        img = self.transform(img)

        phrase = self.corpus.tokenize(region.phrase)
        target = torch.LongTensor([region.x, region.y,
                                   region.width, region.height])
        return img, phrase, target


class VisualGenomeLoaderFull(data.Dataset):
    data_path = 'data'
    processed_folder = 'processed'
    corpus_filename = 'corpus.pt'
    region_file = 'region_descriptions.pt'

    def __init__(self, root, transform=None, target_transform=None,
                 train=False, test=False):
        self.root = root
        self.transform = transform
        # self.cache = {}

        if not osp.exists(self.root):
            raise RuntimeError('Dataset not found ' +
                               'please download it from: ' +
                               'http://visualgenome.org/api/v0/api_home.html')

        if not self.__check_exists():
            self.process_dataset()

        region_path = osp.join(self.data_path, self.processed_folder,
                               self.region_file)

        corpus_file = osp.join(self.data_path, self.processed_folder,
                               self.corpus_filename)

        with open(region_path, 'rb') as f:
            self.region_descriptions = torch.load(f)

        with open(corpus_file, 'rb') as f:
            self.corpus = torch.load(f)

        # region_descriptions = vg.get_all_region_descriptions(
        #     data_dir=self.root)

    def __check_exists(self):
        processed_path = osp.join(self.data_path, self.processed_folder)
        return osp.exists(processed_path)

    def process_dataset(self):
        # print('Processing scene graphs...')
        # vg.add_attrs_to_scene_graphs(self.root)
        # vg.save_scene_graphs_by_id(data_dir=self.root,
        # image_data_dir=self.graph_path)
        # print('Done!')

        try:
            os.makedirs(os.path.join(self.data_path, self.processed_folder))
        except OSError as e:
            if e.errno == errno.EEXIST:
                pass
            else:
                raise

        print("Processing region descriptions...")
        region_descriptions_full = vg.get_all_region_descriptions(
            data_dir=self.root)

        region_descriptions = []
        for region in region_descriptions_full:
            region_descriptions += region

        del region_descriptions_full
        region_path = osp.join(self.data_path, self.processed_folder,
                               self.region_file)

        with open(region_path, 'wb') as f:
            torch.save(region_descriptions, f)

        print("Generating text corpus...")
        corpus = Corpus()
        for i, region in enumerate(region_descriptions):
            print("Processing region: {0}".format(i))
            corpus.add_to_corpus(region.phrase)
            # for region in image_regions:

        corpus.dictionary.add_word('<unk>')

        corpus_file = osp.join(self.data_path, self.processed_folder,
                               self.corpus_filename)

        print("Saving corpus...")
        with open(corpus_file, 'wb') as f:
            torch.save(corpus, f)

        print("Done!")

    def __len__(self):
        return len(self.region_descriptions)

    def __getitem__(self, idx):
        region = self.region_descriptions[idx]
        image_info = region.image

        # if image_info.id not in self.cache:
        image_path = image_info.url.split('/')[-2:]
        image_path = osp.join(self.root, *image_path)
        img = Image.open(image_path).convert('RGB')
        # self.cache[image_info.id] = img

        # img = self.cache[image_info.id]
        img = self.transform(img)

        phrase = self.corpus.tokenize(region.phrase)
        target = torch.LongTensor([region.x, region.y,
                                   region.width, region.height])
        return img, phrase, target
