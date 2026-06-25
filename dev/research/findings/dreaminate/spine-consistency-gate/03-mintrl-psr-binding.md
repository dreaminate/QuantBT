# FINDING · MinTRL + PSR 经脊柱绑定（交叉校验恒等式·接 run verdict cold_start）

- **蒸馏自**:Bailey & López de Prado 2012（PSR / MinTRL） · 现有 `eval/dsr.py`（main 新增 PSR/MinTRL） · 消费点 `run_verdict._cold_start_evidence` · finding `01/02` · 决策 D-MATH-SPINE
- **证据强度**:强——MinTRL/PSR 有两条**精确交叉校验恒等式**（解析可证伪，非统计）：① n=MinTRL → PSR(SR*)≡confidence；② PSR(r, E[max_N]) ≡ DSR(r, N)（绑回已绑 DSR）。漂移即恒等式破。
- **适用域**:成立 = 收益近 IID、SR_pp>SR*、confidence∈(0.5,1)。**不成立边界**:自相关下 √(n−1) 高估有效样本 → PSR/MinTRL 高估显著性（R5 披露）；短样本自估矩噪声大。

## 核心主张（可证伪）[必填]

```text
PSR(SR*) = Φ((SR_pp − SR*)·√(n−1)/denom)            denom=√(1 − γ3·SR_pp + (γ4−3+2)/4·SR_pp²)
MinTRL   = 1 + denom²·(Φ⁻¹(p)/(SR_pp−SR*))²          ——PSR 的解析反解

交叉校验恒等式（命门，解析可证）：
  M1: 把 n=MinTRL 代回 PSR 的 z → z = δ·√(denom²·(zp/δ)²)/denom = |zp| → Φ(z)=Φ(Φ⁻¹(p))=p=confidence
  M4: PSR(r, sr*=E[max_N]) ≡ DSR(r, N)（dsr.py 自陈 V-path 恒等 <1e-12；绑回已绑 DSR）
```

**如果** `minimum_track_record_length`/`probabilistic_sharpe_ratio` 偏离定义（如 denom² 错项 / 丢 sr_benchmark / 反解错），**则** M1/M4 恒等式破 → 脊柱一致性检查 fail → `_cold_start_evidence` 的 cold_start 证据被标 dsr_applicable=False + 数学一致性失败 note（呈现层诚实标，不假绿灯）。

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| `app/backend/app/eval/dsr.py` | `probabilistic_sharpe_ratio`/`minimum_track_record_length`/`_skew`/`_kurt_excess` | 被绑定实现；整链进指纹 |
| `app/backend/app/eval/spine_bindings.py` | 扩展 | PSR/MinTRL artifact + 交叉校验性质 + pinned + verify_mintrl_consistency |
| `app/backend/app/run_verdict.py` | `_cold_start_evidence` | 注入 spine_consistency；漂移→dsr_applicable=False + note（呈现层 fail-soft） |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. M1 交叉校验：多 fixture/confidence → PSR(n=MinTRL)≈confidence（实证 <1e-9）；种 MinTRL 漂移（denom2→1 / 丢 sr_benchmark）→ M1 fail → 门拒。
2. M4 PSR-DSR 互校验：PSR(r,E[max])==DSR(r,N)；种 PSR 漂移 → M4 fail。
3. abstain 诚实：n<3→insufficient、SR≤SR*→never_significant（漂移成 ok=假绿灯→抓）。
4. tripwire：pinned==源指纹（改 dsr.py PSR/MinTRL 链即硬失败）。
5. 生产 wire：cold_start 含 spine_consistency；MinTRL 一致→dsr_applicable 不变；漂移→dsr_applicable=False+note。

## 复用 [按需]
`lineage/spine_binder`（指纹 + property 一致性）· `spine_gate.evaluate_promotion` · 已绑 DSR（M4 互校验）· DSR 切片范式（pinned+tripwire+fail-soft）。

## 未验证残余（诚实）[必填]
- M1/M4 是精确恒等式（强于纯统计 property），但仍不证明「定义本身对」（靠文献+Verifier）。
- cold_start 是**呈现层**（不动治理闸门/三态裁决）→ 这里 fail-soft = 诚实标 dsr_applicable=False + note，**非**阻断 promote（promote 闸门是 run_overfit_gate，已三支脊柱治理）。
- 仍只覆盖信任层三角 + MinTRL/PSR；conformal/attribution/drift 等其余数学点后续。

## → 拆成的任务（本切片实现，落 done）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | MinTRL/PSR 漂移→交叉校验恒等式 fail→cold_start 标 dsr_applicable=False；接 run verdict | P0 | b85e34cc(三角补齐) |
