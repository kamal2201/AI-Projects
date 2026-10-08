import torch
print(f"PyTorch Version: {torch.__version__}")

# --- Critical Check ---
if torch.backends.mps.is_available():
    mps_device = torch.device("mps")
    print("✅ SUCCESS! PyTorch detects the Apple Metal Performance Shaders (MPS) backend.")
    # Optionally, test if MPS works by creating a simple tensor
    x = torch.rand(2, 2, device=mps_device)
    print("Successfully created a tensor on MPS.")
else:
    cpu_device = torch.device("cpu")
    print("❌ FAILURE: PyTorch is running on CPU.")