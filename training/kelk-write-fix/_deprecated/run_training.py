"""Re-run E4B LoRA training with corrected LoRA dimension handling."""
import sys
from pathlib import Path

# Use mlx_vlm from the vendor checkout
sys.path.insert(0, "/Users/nesbitt/dev/vendor/mlx-vlm")

import mlx.core as mx
import mlx.nn as nn
from mlx_vlm.utils import load_model, get_model_path
from mlx_vlm.trainer.utils import (
    get_peft_model,
    find_all_linear_names,
    save_adapter,
)
from mlx_vlm.trainer.sft_trainer import TrainingArgs, train
from mlx_vlm.trainer.datasets import ChatDataset

MODEL_PATH = Path("/Users/nesbitt/models/gemma-4-e4b-it-6bit")
DATA_PATH = Path("/Users/nesbitt/dev/tuning-wizard/exports/kelk_20260412_232123")
ADAPTER_PATH = Path("/Users/nesbitt/dev/factory/training/kelk-write-fix/e4b-adapter")

RANK = 8
ALPHA = 20.0
DROPOUT = 0.0
NUM_LAYERS = 16
ITERS = 200
BATCH_SIZE = 1
LR = 1e-5
MAX_SEQ_LENGTH = 2048

print("Loading model...")
model = load_model(MODEL_PATH, trust_remote_code=True)

# Get processor for tokenization
from mlx_vlm.utils import load_processor
processor = load_processor(MODEL_PATH, trust_remote_code=True)

# Apply LoRA to last NUM_LAYERS layers only
linear_layers = find_all_linear_names(model.language_model)
print(f"Linear layers found: {linear_layers}")

# Freeze everything, then apply LoRA
model = get_peft_model(
    model,
    linear_layers,
    rank=RANK,
    alpha=ALPHA,
    dropout=DROPOUT,
    freeze=True,
    verbose=True,
)

# Set up optimizer
optimizer = mx.optimizers.Adam(learning_rate=LR)

# Load datasets
print("Loading datasets...")
train_dataset = ChatDataset(
    data_path=DATA_PATH,
    processor=processor,
    max_seq_length=MAX_SEQ_LENGTH,
    split="train",
)
val_dataset = ChatDataset(
    data_path=DATA_PATH,
    processor=processor,
    max_seq_length=MAX_SEQ_LENGTH,
    split="valid",
)
print(f"Train: {len(train_dataset)} examples, Val: {len(val_dataset)} examples")

# Training args
args = TrainingArgs(
    batch_size=BATCH_SIZE,
    iters=ITERS,
    learning_rate=LR,
    steps_per_report=10,
    steps_per_eval=200,
    steps_per_save=100,
    max_seq_length=MAX_SEQ_LENGTH,
    adapter_file=str(ADAPTER_PATH / "adapters.safetensors"),
    grad_checkpoint=True,
)

print(f"Starting training for {ITERS} iterations...")
train(
    model=model,
    optimizer=optimizer,
    train_dataset=train_dataset,
    val_dataset=val_dataset,
    args=args,
)

# Save final adapter
print("Saving adapter...")
save_adapter(model, ADAPTER_PATH, args)
print(f"Done. Adapter saved to {ADAPTER_PATH}")
