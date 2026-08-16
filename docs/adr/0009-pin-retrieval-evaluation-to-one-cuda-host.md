# Pin retrieval evaluation to one CUDA host

CUDA Retrieval Evaluation Runs target one reproducible host profile: Ubuntu 20.04 on x86_64, NVIDIA driver 550.142, one 8 GiB RTX 2070-class GPU, Python 3.13, and PyTorch 2.6.0 with CUDA 12.4. This deliberately favors comparable results and a fully pinned environment over portability; automatic adaptation to other operating systems, GPUs, drivers, or CUDA versions is outside this runner's scope.
