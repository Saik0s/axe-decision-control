# Local inference performance

Created: 2026-10-05T17:00:19.896388+00:00

Host: Apple M2 Ultra; RAM bytes: 68719476736.
Python: 3.13.9; platform: macOS-27.0.1-arm64-arm-64bit-Mach-O.
Architecture: arm64; logical CPUs: 24.
Packages: {"Pillow": "12.3.0", "axe-decision-control": "0.1.0", "httpx": "0.28.1", "pydantic": "2.13.5"}.
Model: Winnow-12B; PID: 93412.
Discovery: [{"health_status": "ok", "http_status": 200, "issue": null, "models": [], "route": "/health", "verified": true}, {"health_status": null, "http_status": 200, "issue": null, "models": [{"ftype": "Q8_0", "id": "Winnow-12B", "n_ctx": 8192, "n_params": 11907350576, "size": 12653822144}], "route": "/v1/models", "verified": true}].
Operator-declared launch: {"context_capacity":8192,"backend":"Metal","device":"Apple M2 Ultra","quantization":"Q8_0","kv_cache":"F16","projector_loaded":true,"parallel":1,"winnow_commit":"77d14580c6732ca2f3745750c1dc1fd446d8bcee","llama_cpp_commit":"911f6cdc8ab8a530b2bee09ee61471a6f3178eeb"}.

Cold means prefix reuse disabled, not model startup or filesystem-cache cold.
Warm requires cache_hit=true and prefix_reused_tokens>0 for every included sample.
Ratios require every attempt valid and at least 3 samples per regime, plus setup.
p95 is nearest-rank sample p95; at n=5 it is the maximum, not tail proof.
RSS/CPU are whole-process observations in request windows, not request allocations.
Backend allocation/budget describes the backend/device, not a per-request peak.
CPU is ps percent, not energy. No calibrated quality or capacity claim.

## text-small-1q

Questions: 1; image dimensions: 0 x 0.
Observed state_bytes, all attempts including setup/errors: 360 to 360 (n=11).
Observed input_tokens, all attempts including setup/errors: 213 to 213 (n=11).
Observed image_tokens, all attempts including setup/errors: 0 to 0 (n=11).
Observed unique_questions, all attempts including setup/errors: 1 to 1 (n=11).
Observed backend_allocated_bytes, all attempts including setup/errors: 14664105984 to 14664105984 (n=11).
Observed backend_budget_bytes, all attempts including setup/errors: 55662788608 to 55662788608 (n=11).
cold: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 415.536, min 412.169, max 7653.479, sample p95 7653.479
- request_ms: n=5, median 415.344, min 411.986, max 7653.168, sample p95 7653.168
- native_ms: n=5, median 409.854, min 409.174, max 7649.034, sample p95 7649.034
- prefill_ms: n=5, median 261.992, min 260.823, max 7215.408, sample p95 7215.408
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 261.992, min 260.823, max 7215.408, sample p95 7215.408
- queue_ms: n=5, median 0.020, min 0.014, max 0.047, sample p95 0.047
warm: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 136.452, min 135.460, max 137.156, sample p95 137.156
- request_ms: n=5, median 136.201, min 135.312, max 136.960, sample p95 136.960
- native_ms: n=5, median 134.134, min 133.399, max 134.258, sample p95 134.258
- prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- queue_ms: n=5, median 0.016, min 0.011, max 0.024, sample p95 0.024
Cold/warm wall median ratio: 3.045281953318733.

## text-medium-8q

Questions: 8; image dimensions: 0 x 0.
Observed state_bytes, all attempts including setup/errors: 1914 to 1914 (n=11).
Observed input_tokens, all attempts including setup/errors: 1107 to 1107 (n=11).
Observed image_tokens, all attempts including setup/errors: 0 to 0 (n=11).
Observed unique_questions, all attempts including setup/errors: 8 to 8 (n=11).
Observed backend_allocated_bytes, all attempts including setup/errors: 14664105984 to 14664105984 (n=11).
Observed backend_budget_bytes, all attempts including setup/errors: 55662788608 to 55662788608 (n=11).
cold: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 2151.044, min 2148.182, max 2157.878, sample p95 2157.878
- request_ms: n=5, median 2150.776, min 2147.881, max 2157.568, sample p95 2157.568
- native_ms: n=5, median 2148.613, min 2145.774, max 2155.456, sample p95 2155.456
- prefill_ms: n=5, median 997.182, min 995.151, max 1000.671, sample p95 1000.671
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 997.182, min 995.151, max 1000.671, sample p95 1000.671
- queue_ms: n=5, median 0.016, min 0.010, max 0.022, sample p95 0.022
warm: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 1141.276, min 1138.394, max 1141.881, sample p95 1141.881
- request_ms: n=5, median 1140.962, min 1138.109, max 1141.479, sample p95 1141.479
- native_ms: n=5, median 1138.177, min 1135.890, max 1138.915, sample p95 1138.915
- prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- queue_ms: n=5, median 0.036, min 0.020, max 0.184, sample p95 0.184
Cold/warm wall median ratio: 1.8847715813742203.

## text-large-16q

Questions: 16; image dimensions: 0 x 0.
Observed state_bytes, all attempts including setup/errors: 5072 to 5072 (n=11).
Observed input_tokens, all attempts including setup/errors: 2607 to 2607 (n=11).
Observed image_tokens, all attempts including setup/errors: 0 to 0 (n=11).
Observed unique_questions, all attempts including setup/errors: 16 to 16 (n=11).
Observed backend_allocated_bytes, all attempts including setup/errors: 14664105984 to 14664105984 (n=11).
Observed backend_budget_bytes, all attempts including setup/errors: 55662788608 to 55662788608 (n=11).
cold: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 5196.441, min 5188.114, max 5214.727, sample p95 5214.727
- request_ms: n=5, median 5196.008, min 5187.683, max 5214.325, sample p95 5214.325
- native_ms: n=5, median 5193.621, min 5184.449, max 5210.114, sample p95 5210.114
- prefill_ms: n=5, median 2625.915, min 2614.744, max 2640.249, sample p95 2640.249
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 2625.915, min 2614.744, max 2640.249, sample p95 2640.249
- queue_ms: n=5, median 0.020, min 0.012, max 0.023, sample p95 0.023
warm: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 2549.916, min 2548.689, max 2551.605, sample p95 2551.605
- request_ms: n=5, median 2549.514, min 2548.268, max 2551.162, sample p95 2551.162
- native_ms: n=5, median 2547.447, min 2545.755, max 2548.803, sample p95 2548.803
- prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- queue_ms: n=5, median 0.017, min 0.012, max 0.022, sample p95 0.022
Cold/warm wall median ratio: 2.0378872463702815.

## text-many-32q

Questions: 32; image dimensions: 0 x 0.
Observed state_bytes, all attempts including setup/errors: 1914 to 1914 (n=11).
Observed input_tokens, all attempts including setup/errors: 2535 to 2535 (n=11).
Observed image_tokens, all attempts including setup/errors: 0 to 0 (n=11).
Observed unique_questions, all attempts including setup/errors: 32 to 32 (n=11).
Observed backend_allocated_bytes, all attempts including setup/errors: 14664105984 to 14664105984 (n=11).
Observed backend_budget_bytes, all attempts including setup/errors: 55662788608 to 55662788608 (n=11).
cold: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 5581.380, min 5576.802, max 5588.164, sample p95 5588.164
- request_ms: n=5, median 5581.081, min 5576.467, max 5587.845, sample p95 5587.845
- native_ms: n=5, median 5578.570, min 5573.627, max 5585.122, sample p95 5585.122
- prefill_ms: n=5, median 996.459, min 995.141, max 998.092, sample p95 998.092
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 996.459, min 995.141, max 998.092, sample p95 998.092
- queue_ms: n=5, median 0.020, min 0.012, max 0.025, sample p95 0.025
warm: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 4569.922, min 4567.639, max 4575.456, sample p95 4575.456
- request_ms: n=5, median 4569.595, min 4567.260, max 4575.139, sample p95 4575.139
- native_ms: n=5, median 4566.919, min 4564.491, max 4572.466, sample p95 4572.466
- prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- queue_ms: n=5, median 0.018, min 0.014, max 0.023, sample p95 0.023
Cold/warm wall median ratio: 1.2213294636796264.

## image-256-1q

Questions: 1; image dimensions: 256 x 256.
Observed state_bytes, all attempts including setup/errors: 360 to 360 (n=11).
Observed input_tokens, all attempts including setup/errors: 303 to 303 (n=11).
Observed image_tokens, all attempts including setup/errors: 81 to 81 (n=11).
Observed unique_questions, all attempts including setup/errors: 1 to 1 (n=11).
Observed backend_allocated_bytes, all attempts including setup/errors: 14664105984 to 14664105984 (n=11).
Observed backend_budget_bytes, all attempts including setup/errors: 55662788608 to 55662788608 (n=11).
cold: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 724.529, min 721.180, max 741.209, sample p95 741.209
- request_ms: n=5, median 724.296, min 721.007, max 740.968, sample p95 740.968
- native_ms: n=5, median 722.044, min 719.006, max 738.530, sample p95 738.530
- prefill_ms: n=5, median 566.559, min 565.894, max 581.893, sample p95 581.893
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 566.559, min 565.894, max 581.893, sample p95 581.893
- queue_ms: n=5, median 0.021, min 0.011, max 0.079, sample p95 0.079
warm: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 140.275, min 139.404, max 144.791, sample p95 144.791
- request_ms: n=5, median 139.996, min 139.205, max 144.355, sample p95 144.355
- native_ms: n=5, median 137.738, min 137.196, max 138.966, sample p95 138.966
- prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- queue_ms: n=5, median 0.024, min 0.013, max 1.065, sample p95 1.065
Cold/warm wall median ratio: 5.165064607000889.

## image-phone-portrait-4q

Questions: 4; image dimensions: 402 x 874.
Observed state_bytes, all attempts including setup/errors: 974 to 974 (n=11).
Observed input_tokens, all attempts including setup/errors: 728 to 728 (n=11).
Observed image_tokens, all attempts including setup/errors: 144 to 144 (n=11).
Observed unique_questions, all attempts including setup/errors: 4 to 4 (n=11).
Observed backend_allocated_bytes, all attempts including setup/errors: 14668742656 to 14668742656 (n=11).
Observed backend_budget_bytes, all attempts including setup/errors: 55662788608 to 55662788608 (n=11).
cold: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 1692.739, min 1609.491, max 1777.992, sample p95 1777.992
- request_ms: n=5, median 1692.491, min 1609.221, max 1777.698, sample p95 1777.698
- native_ms: n=5, median 1690.295, min 1607.128, max 1775.493, sample p95 1775.493
- prefill_ms: n=5, median 1030.587, min 965.223, max 1088.197, sample p95 1088.197
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 1030.587, min 965.223, max 1088.197, sample p95 1088.197
- queue_ms: n=5, median 0.024, min 0.014, max 0.027, sample p95 0.027
warm: 5/5 valid; failures 0; regime verified True.
- wall_ms: n=5, median 627.941, min 622.379, max 638.163, sample p95 638.163
- request_ms: n=5, median 627.573, min 622.108, max 637.915, sample p95 637.915
- native_ms: n=5, median 625.304, min 620.001, max 635.849, sample p95 635.849
- prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- request_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- provider_prefill_ms: n=5, median 0.000, min 0.000, max 0.000, sample p95 0.000
- queue_ms: n=5, median 0.016, min 0.012, max 0.020, sample p95 0.020
Cold/warm wall median ratio: 2.695698466625344.

All-attempt reported cost USD: unavailable; unpriced attempts: 66.
Whole-process RSS observed maximum KiB: 1565152; CPU observed maximum ps percent: 79.6; resource observations: 1430.

Setup attempts are separate and excluded from latency summaries. All attempts,
numeric token/native/cost evidence, errors and RSS/CPU are in results.json.
Missing metrics and unreported costs remain null, never inferred as zero.
