# W7 · 引用核验 Agent（verifier/reflection）— 启示 83

**结论**：⭐ agent 深化 ②：LLM verifier 逐项核对答案里规范号/条文号/数字/强条是否被 chunks 支持，
补规则式治理的缺口——**规则能剥"补充说明"、校量词、查 [N] 角标，但抓不到"假规范号 / 错数字"这类编造**。
控制实验实证：verifier 抓出植入的 `GB 99999-2099`、`500m`、`2000m²` 三处编造，且对有据答案零误报。
沉淀 **启示 83**（规则治理 + LLM 核验分工：确定性规则打常见、LLM verifier 兜语义编造）。

---

## 一、诊断：规则治理的缺口

现有 `post_filter` 覆盖：
- `strip_supplementary_sections`（剥"补充说明"节，治 dim7 编造惯性）
- `align_modal_verbs`（校"应/宜/不应"量词与 chunks 一致）
- `detect_number/modal_diffs`（检测差异，metadata 警告）
- dangling `[N]`（查引用角标越界）

**缺口**：`align_numbers` 已回滚（启示 62，自动改数字比量词危险）→ 数字编造只检测不拦；
**规范号 / 条文号编造无人验**——LLM 若引一个"看着对但 chunks 里没有"的规范号，
dangling 只查 `[N]` 角标索引、不查规范号文本，规则抓不到。这是红线 1（不编造）的真实防线缺口。

## 二、构建

- `rag/verifier.py`：`verify_grounding(answer, chunks)` → `{grounded, issues, verified}`。
  LLM verifier 只核四类硬事实（规范号/条文号/数字/强条用语），prompt 要求"宁可漏报不误报"。
- `core/prompts.py`：verifier prompt（核对规则 + JSON verdict 格式）。
- `core/config.py`：`ANSWER_VERIFY_ENABLED` flag（默认关）。
- `pipeline.py`：生成 + 后处理后核验，结果进 metadata（`grounding_verified/ok/issues`）。
  **第一版只检测不改写**（自动改答案有风险，见 align_numbers 回滚），失败降级"未核验"不阻塞。
- 单测 6 条（verdict 解析 + 一致性），全套 87 测试通过。

## 三、🎯 控制实验：verifier 抓住规则抓不到的编造

手造 chunks（内容可控），对比有据答案 vs 植入编造的答案：

| 答案 | grounded | verifier 输出 |
|---|---|---|
| ① 有据（300m / 1500m²，与片段一致） | ✅ True | 无 issue（**零误报**）|
| ② 植入编造（500m / GB 99999-2099《城市绿化条例》/ 2000m² / 不应） | ❌ False | 抓出 3 处：数字+用语双错、**假规范号/标准名/条文号片段中不存在**、数字错 |

**第 2 处（假规范号 GB 99999-2099）正是 dangling / align 规则抓不到的缺口**——
它 `[N]` 角标没越界、量词也没错，纯粹是"引了一个不存在的规范"，只有语义核验能抓。

生产验证：真实 query 走 pipeline，`grounding_verified=True / grounding_ok=True / issues=[]`（正常答案不误伤）。

## 四、🎓 启示 83 · 规则治理与 LLM 核验的分工 ⭐

**确定性规则和 LLM 核验不是二选一，是分工：**
- **规则**：打**高频、可模式化**的错（"补充说明"节、量词不一致、`[N]` 越界）——快、免费、稳定、可单测。
- **LLM verifier**：兜**语义级、难模式化**的编造（假规范号、张冠李戴的数字）——规则写不出正则，只能靠理解。

**对 AIPM 转行的启示**：
- **别用一种手段包打天下**。规则治理把 dim7 从 76.7% 拉到 97%（启示 54），但剩下的 3% 是语义编造，
  规则再堆也抓不到——这时该上 verifier，而不是继续写正则。**知道每种手段的能力边界**。
- **防线要分层**（defense in depth）：规则 + 核验 + 兜底，红线 1 才守得住。单点防线迟早漏。
- **第一版只检测不改写是有意的**：自动改生成文本风险高（align_numbers 就因此回滚）。
  先把编造"看见"（metadata + 提示），改写/重生成留作下一步——**先可观测，再自动化**。

## 五、成本与默认关

verifier 对每个答案加一次 LLM 调用（核验）。默认关，因为：
- 多数答案本就有据，给全部加一次核验不划算，且压总时延 SLA。
- **未来**：只对"含数字/规范号密度高"或"检索相关度低"的答案触发核验（省调用）；
  以及把 issues 从"检测"升级为"重生成"闭环。

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `backend/app/rag/verifier.py` | 新建：LLM 引用核验 |
| `backend/app/core/prompts.py` | +verifier prompt |
| `backend/app/core/config.py` | +ANSWER_VERIFY_* flag |
| `backend/app/rag/pipeline.py` | 接入核验 → metadata grounding 字段（默认关）|
| `backend/tests/test_verifier.py` | 新建：6 条 verdict 解析单测 |
| `docs/devlog/2026-W7_verifier_agent.md` | 本文件 |

---

**日志版本**：v1.0
**最后更新**：2026-W7（agent 深化 · 引用核验）
**累计洞察**：**83 个**（+启示 83 规则治理 + LLM 核验分工）
**项目状态**：引用核验 Agent 已生产化（默认关 + flag）· 补规则缺口（假规范号/错数字语义编造）· 第一版只检测不改写
