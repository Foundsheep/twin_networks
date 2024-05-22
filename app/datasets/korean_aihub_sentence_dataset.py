import torch
from pathlib import Path
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import numpy as np
import json
import time
import albumentations as A


class KoreanTypographyDataset(Dataset):
    def __init__(self, root_dir, transform=None, is_train=True, is_sanity_check=None) -> None:
        super().__init__()
        self.root_dir = root_dir
        self.transform = transform
        self.is_train = is_train
        self.is_sanity_check = is_sanity_check
        self.image_path_list, self.label_list = self.read_paths()
        self.label2int_map = self.label_to_integer()

    def __len__(self):
        return len(self.label_list)

    # TODO: check if the model consumes all the data really
    def __getitem__(self, idx):
        anchor_label = self.label_list[idx]
        label_arr = np.array(self.label_list)
        pos_indices = np.where(label_arr == anchor_label)[0]
        pos_indices = np.delete(pos_indices, np.where(pos_indices == idx))
        neg_indices = np.where(label_arr != anchor_label)[0]

        pos_idx = np.random.choice(pos_indices)
        neg_idx = np.random.choice(neg_indices) 
        
        # get images
        anchor_img = self.read_image(idx)
        pos_img = self.read_image(pos_idx)
        neg_img = self.read_image(neg_idx)
        
        # augmentation
        if self.transform:
            anchor_img = self.transform(image=anchor_img)["image"]
            pos_img = self.transform(image=pos_img)["image"]
            neg_img = self.transform(image=neg_img)["image"]

        anchor_img = self.convert_to_tensor(anchor_img)
        pos_img = self.convert_to_tensor(pos_img)
        neg_img = self.convert_to_tensor(neg_img)

        # label = self.label2int_map[self.label_list[idx]]
        return anchor_img, pos_img, neg_img

    def read_paths(self):
        p = Path(self.root_dir) / f"{'Training' if self.is_train else 'Validation'}"

        image_p = p / "01.원천데이터" / f"{'T' if self.is_train else 'V'}S_images"
        label_p = p / "02.라벨링데이터" / f"{'T' if self.is_train else 'V'}L_labels"
        
        # set the return lists
        label_list = []
        image_path_list = []

        start = time.time()        
        for i_sen, (img_sen, lab_sen) in enumerate(zip(image_p.glob("*"), label_p.glob("*"))):
            for i_tf, (img_tf, lab_tf) in enumerate(zip(img_sen.glob("*"), lab_sen.glob("*"))):
                
                # 자필 폴더만 사용(모사는 정확히 본인 글씨체가 아니니)
                if "모사" in str(img_tf.parts[-1]):
                    continue
                    
                # 담기 시작
                img_tf = list(img_tf.glob("*"))
                lab_tf = list(lab_tf.glob("*"))
                assert len(img_tf) == len(lab_tf), f"{len(img_tf) = }, {len(lab_tf) = }, {img_tf[0] = }, {lab_tf[0] = }"  # check if the number of subfolders is the same
                
                number_of_labels = len(lab_tf)
                
                # 윗 단계에서 라벨 경로 먼저 구하고
                label_path = lab_tf[0] / "labels(sent1).json"
                
                # 이미지는 폴더들마다 마지막꺼가 필요하니 for loop
                for img_pos, lab_pos in zip(img_tf, lab_tf):
                    image_path = list(img_pos.glob("*_0150_x*"))[0]
                                        
                    # 혹시 쓴 사람에 대한 정보가 다르다면 assert
                    assert image_path.parts[-3] == label_path.parts[-3], f"{image_path.parts[-3] = }, {label_path.parts[-3] = }"
                    image_path_list.append(str(image_path))
                
                # 라벨은 다 같으니 json io 한번해서 한꺼번에 넣기
                with open(label_path, "r", encoding="utf-8-sig") as f:
                    j = json.load(f)
                label = j["person"]["id"]
                    
                temp_list = [label] * number_of_labels
                label_list.extend(temp_list)
                
                # 모델 확인을 위한 소규모 데이터셋 가져오기
                if self.is_sanity_check is not None and self.is_sanity_check is True:
                    if self.is_train and i_tf == 3:
                        break
                    elif not self.is_train and i_tf == 1:
                        break
            if self.is_sanity_check is not None and self.is_sanity_check is True:
                if self.is_train and i_sen == 3:
                    break
                elif not self.is_train and i_sen == 1:
                    break
                        
        end = time.time()
        assert len(image_path_list) == len(label_list)
        print(f"read paths done! it took [{end - start :.2f}] seconds, got [{len(label_list)}] labels")
        return image_path_list, label_list

    def label_to_integer(self):
        return_dict = dict()
        for i, val in enumerate(np.unique(self.label_list)):
            return_dict[val] = str(i)
        return return_dict

    def get_label_from_json(self, label_path):
        with open(label_path, "r", encoding="utf-8-sig") as f:
            j = json.load(f)
            label = j["person"]["id"]

        return label

    def read_image(self, idx):
        image_path = self.image_path_list[idx]
        io_result = False

        io_idx = -1        
        while io_result is False:
            try:
                image = Image.open(image_path)  # there was a case when 150th image was not valid
                io_result = True
            except:
                # get an image file one frame before the last one and on and on
                io_idx -= 1

                # get the new image path
                p = Path(image_path)
                folder = p.parent
                files = list(folder.glob("*"))
                image_path = files[io_idx]

        image = np.array(image)[:, :, :3]  # image has alpha channel -> 4 channels
        return image
    
    def convert_to_tensor(self, image):
        # convert to torch.tensor
        image = image.transpose((2, 0, 1))
        image = torch.tensor(image, dtype=torch.float32)
        return image


def get_dataloader(root_dir, is_train, is_sanity_check, batch_size, shuffle):

    # transform
    transform = A.Compose(
        [
            A.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225))
        ]
    )

    # make dataset
    ds = KoreanTypographyDataset(root_dir, transform, is_train, is_sanity_check)
    dl = DataLoader(ds, batch_size, shuffle)
    return dl