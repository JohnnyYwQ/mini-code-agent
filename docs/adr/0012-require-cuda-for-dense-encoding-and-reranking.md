# Require CUDA for dense encoding and reranking

A CUDA Retrieval Evaluation Run binds both the E5 dense encoder and BGE reranker to `cuda:0`, uses FP16 for BGE on the pinned RTX 2070-class GPU, and fails if either model falls back to CPU. This adds a CUDA-specific FastEmbed environment and stricter model preflight, but prevents a nominally CUDA run from spending its dominant indexing phase on CPU and makes accepted baselines comparable on the fixed host.
