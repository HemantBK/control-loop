"""extract.py <rotary_embedding.cu> <out.inc>: the kernel template (from `template <typename scalar_t>` to the line before
the host wrapper), verbatim. Fails loudly if the markers are not found."""
import sys
src = open(sys.argv[1]).read()
a = src.index("template <typename scalar_t>")
b = src.index("torch::Tensor agent_rotary_embedding")
body = src[a:b]
cut = body.rfind("// ───")          # drop the "Host wrapper" banner comment if present
body = body[:cut] if cut > body.rfind("}") - 5 and cut != -1 else body
open(sys.argv[2], "w").write(body); print(sys.argv[2], len(body.splitlines()), "lines")
