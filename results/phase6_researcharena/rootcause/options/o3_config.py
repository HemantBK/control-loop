"""Option 3 check 1 (Amendment (14)): the candidate's config from the HF hub, gating, and the per-token RoPE pair counts."""
import json, sys, urllib.request
for mid in sys.argv[1:]:
    info = json.load(urllib.request.urlopen(f"https://huggingface.co/api/models/{mid}"))
    cfg = json.load(urllib.request.urlopen(f"https://huggingface.co/{mid}/resolve/main/config.json"))
    H = cfg["num_attention_heads"]; KV = cfg.get("num_key_value_heads", H)
    hd = cfg.get("head_dim") or cfg["hidden_size"] // H
    qp, kp = H * hd // 2, KV * hd // 2
    print(f"{mid} | gated={info.get('gated')} private={info.get('private')} sha={info.get('sha')}")
    print(f"  architectures={cfg.get('architectures')} model_type={cfg.get('model_type')} hidden={cfg['hidden_size']} "
          f"layers={cfg['num_hidden_layers']} heads={H} kv_heads={KV} head_dim={hd} intermediate={cfg.get('intermediate_size')} "
          f"vocab={cfg.get('vocab_size')} rope_theta={cfg.get('rope_theta')} rope_scaling={cfg.get('rope_scaling')} "
          f"max_pos={cfg.get('max_position_embeddings')} dtype={cfg.get('torch_dtype')}")
    print(f"  pairs/token: q={qp} ({'multiple' if qp % 256 == 0 else 'NOT a multiple'} of 256), "
          f"k={kp} ({'multiple' if kp % 256 == 0 else 'NOT a multiple'} of 256)")
    print("  files:", [s["rfilename"] for s in info.get("siblings", [])])
