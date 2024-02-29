# -*- coding: utf-8 -*-
"""BLIP2_vqarad.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1UgRDQymMG7dvFSlcm6yFaV2NYacmJ0jf
"""

# !pip install -q peft transformers bitsandbytes datasets sacrebleu

from datasets import load_dataset

dataset = load_dataset("flaviagiammarino/path-vqa", split='train[:8000]')

# dataset['question'][0]

# dataset[0]['image'].convert('RGB')

def create_text(example):
    example['text'] = 'Question: ' + example['question'] + ' Answer: ' + example['answer']
    example['image'] = (example['image'].resize((224, 224))).convert('RGB')
    return example

dataset = dataset.map(create_text)

from torch.utils.data import Dataset, DataLoader

class ImageCaptioningDataset(Dataset):
    def __init__(self, dataset, processor):
        self.dataset = dataset
        self.processor = processor

    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, idx):
        item = self.dataset[idx]
        encoding = self.processor(images=item["image"], padding="max_length", return_tensors="pt")
        # remove batch dimension
        encoding = {k: v.squeeze() for k, v in encoding.items()}
        encoding["text"] = item["text"]
        return encoding

def collate_fn(batch):
    # pad the input_ids and attention_mask
    processed_batch = {}
    for key in batch[0].keys():
        if key != "text":
            processed_batch[key] = torch.stack([example[key] for example in batch])
        else:
            text_inputs = processor.tokenizer(
                [example["text"] for example in batch], padding=True, return_tensors="pt"
            )
            processed_batch["input_ids"] = text_inputs["input_ids"]
            processed_batch["attention_mask"] = text_inputs["attention_mask"]
    return processed_batch

from transformers import AutoProcessor, Blip2ForConditionalGeneration

processor = AutoProcessor.from_pretrained("Salesforce/blip2-opt-2.7b")
model = Blip2ForConditionalGeneration.from_pretrained("ybelkada/blip2-opt-2.7b-fp16-sharded", device_map="auto", load_in_8bit=True)

from peft import LoraConfig, get_peft_model

# Let's define the LoraConfig
config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    target_modules=["q_proj", "k_proj"]
)

model = get_peft_model(model, config)
model.print_trainable_parameters()

train_dataset = ImageCaptioningDataset(dataset, processor)
train_dataloader = DataLoader(train_dataset, shuffle=True, batch_size=8, collate_fn=collate_fn)

import torch

optimizer = torch.optim.Adam(model.parameters(), lr=5e-4)

device = "cuda" if torch.cuda.is_available() else "cpu"

model.train()
train_losses = []
train_loss_weight_update = []
running_loss = 0.0

for epoch in range(50):
  print("============================Epoch:", epoch,"=================================")
  for idx, batch in enumerate(train_dataloader):
    input_ids = batch.pop("input_ids").to(device)
    pixel_values = batch.pop("pixel_values").to(device, torch.float16)

    outputs = model(input_ids=input_ids,
                    pixel_values=pixel_values,
                    labels=input_ids)

    loss = outputs.loss

    running_loss += loss.item()
    if(idx%50==0):
      train_loss_weight_update.append(running_loss/((epoch*1000)+((idx+1)*50)))
      print("Loss:", loss.item())

    loss.backward()

    optimizer.step()
    optimizer.zero_grad()
  train_losses.append(loss/len(train_dataloader))

# train_losses = [tensor.cpu().detach().numpy() for tensor in train_losses]
# Specify a path
PATH = "train_losses.pt"

# Save
torch.save(train_losses, PATH)

# Specify a path
PATH = "train_losses_weight_update.pt"

# Save
torch.save(train_loss_weight_update, PATH)

# import matplotlib.pyplot as plt

# fig, axs = plt.subplots(1)

# # First subplot
# axs.plot(train_losses)
# axs.set_xlabel('Epochs')
# axs.set_ylabel('Training Loss')
# axs.set_title('Training Loss per epoch')

# # Display the figure
# plt.tight_layout()
# plt.show()

val_dataset = load_dataset("flaviagiammarino/path-vqa", split='test[:1000]')

# inputs = processor(images=val_dataset[0]['image'].convert('RGB'), return_tensors="pt").to(device, torch.float16)
# pixel_values = inputs.pixel_values

# generated_ids = model.generate(pixel_values=pixel_values, max_length=25)
# generated_caption = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
# print(generated_caption)

# val_dataset[0]['answer']

generated_answers = []

for i in range(len(val_dataset)):
    image = val_dataset[i]['image'].convert('RGB')
    question = val_dataset[i]['question']

    prompt = f"Question: {question} Answer:"

    inputs = processor(image, text=prompt, return_tensors="pt").to(device, torch.float16)
    generated_ids = model.generate(**inputs, max_new_tokens=10)
    generated_text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
    generated_answers.append(generated_text)
    # if(i<10):
    #     print("Question:", question)
    #     print("Generated Answer:", generated_text)
    #     print("Answer:", val_dataset[i]['answer'])
    #     print("------------------------------------")

reference_answers = [[answer] for answer in val_dataset['answer']]

# Save
PATH = "generated_answers.pt"
torch.save(generated_answers, PATH)

# Save
PATH = "original_answers.pt"
torch.save(reference_answers, PATH)

from datasets import load_metric

metric = load_metric("sacrebleu")

metric.add_batch(predictions=generated_answers, references=reference_answers)
bleu_score = metric.compute()

print(f"BLEU score:", bleu_score)

import torch
# Assuming that `model` is your trained model

# Specify a path
PATH = "model_pathvqa_50_epochs.pth"

# Save
torch.save(model.state_dict(), PATH)

