"""管段漏损分诊：可剪枝的决策树与分层留出验证。"""
import numpy as np
from sklearn.tree import DecisionTreeClassifier, export_text
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, f1_score, confusion_matrix

FEATURES = ["night_flow", "pressure_drop", "acoustic_db", "pipe_age"]
LABELS = ["夜间流量(m³/h)", "压力降(kPa)", "声学读数(dB)", "管龄(年)"]


def metadata():
    return {
        "name": "供水漏损分诊实验", "short": "water-triage",
        "tagline": "把历史巡检证据转成可解释分诊规则，先核验漏检代价。",
        "client": "澄川水务 · 城北巡检班12人 · 280个已复核管段样本",
        "workflow": "值班员把夜间流量、压力和听漏记录抄入表格，根据单一声学阈值安排巡查。",
        "pains": ["单阈值遗漏低噪声漏点", "缺少对巡检规则复杂度的控制", "规则好坏只凭训练样本判断"],
        "upstream": "城北分区流量计与人工复核台账 north_zone_segments.csv",
        "downstream": "巡检组长审阅分诊误报和漏检，决定下一轮人工现场检查顺序",
        "entities": ["管段复核样本", "分诊规则试验", "巡检复核简报"],
        "dataset_name": "城北管段夜间流量与已复核标签",
        "columns": [{"key": "segment_id", "label": "管段编号", "type": "string"}] + [{"key": k, "label": l, "type": "number"} for k, l in zip(FEATURES, LABELS)] + [{"key": "confirmed_leak", "label": "复核漏点(1/0)", "type": "number"}],
        "parameters": [{"key": "max_depth", "label": "决策树最大深度", "type": "number", "default": 3, "min": 1, "max": 8}, {"key": "min_leaf", "label": "叶节点最少样本", "type": "number", "default": 5, "min": 2, "max": 20}],
        "workbench_title": "漏损分诊规则试验", "action_label": "训练并核验分诊规则", "unit": "段管线",
        "accent": "oklch(48% 0.10 210)", "style": "blueprint",
        "seed_story": ["07:30 值班员导入 north_zone_segments.csv 的280段历史复核记录", "07:40 检查夜间流量、压力降、声学读数与管龄", "08:00 用深度3、最小叶节点5发起规则试验", "08:01 系统固定保留30%样本用于独立核验", "08:10 组长先看漏检数量，再看特征重要性", "08:20 将深度从3调为5比较验证F1", "08:30 下载管段分诊明细，选择现场复核清单", "09:00 管理员安排次日07:30规则复核简报"],
        "method": "分层70/30留出，random_state=42；Gini决策树按max_depth和min_samples_leaf剪枝；在留出集计算精确率、召回率和F1。",
        "limitations": ["模拟历史样本不能替代听漏与开挖确认", "未使用空间邻接关系", "特征重要性反映模型分裂贡献而非因果"],
    }


def seed_records():
    rng = np.random.default_rng(1009)
    rows = []
    for i in range(280):
        flow = float(np.clip(rng.normal(23, 10), 2, 60))
        pressure = float(np.clip(rng.gamma(2.2, 5), 0.5, 40))
        sound = float(np.clip(rng.normal(42, 12), 12, 85))
        age = int(rng.integers(1, 46))
        leak = (flow > 26 and pressure > 10) or (sound > 50 and age > 18) or pressure > 25
        if rng.random() < 0.07:
            leak = not leak
        rows.append({"segment_id": f"NC-{i+1:03}", "night_flow": round(flow, 2), "pressure_drop": round(pressure, 2), "acoustic_db": round(sound, 1), "pipe_age": age, "confirmed_leak": int(leak)})
    return rows


def analyze(records, params):
    try:
        depth_raw = float(params.get("max_depth", 3))
        leaf_raw = float(params.get("min_leaf", 5))
        depth, leaf = int(depth_raw), int(leaf_raw)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("树深度与最小叶节点须为整数。") from exc
    if depth != depth_raw or leaf != leaf_raw or not 1 <= depth <= 8 or not 2 <= leaf <= 20:
        raise ValueError("树深度须为1~8，最小叶节点须为2~20，且都为整数。")
    if len(records) < 40:
        raise ValueError("至少需要40条管段复核样本。")
    try:
        x = np.asarray([[float(row[k]) for k in FEATURES] for row in records])
        y_raw = np.asarray([float(row["confirmed_leak"]) for row in records])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("管段字段必须完整且为数值。") from exc
    if not np.isfinite(x).all() or (x < 0).any() or not np.isin(y_raw, [0, 1]).all():
        raise ValueError("测量值须非负有限，复核标签须为0/1。")
    y = y_raw.astype(int)
    if np.bincount(y, minlength=2).min() < 8:
        raise ValueError("漏点与非漏点样本各至少8条。")
    train, valid = train_test_split(np.arange(len(y)), test_size=0.3, stratify=y, random_state=42)
    model = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=leaf, random_state=42)
    model.fit(x[train], y[train])
    probability = model.predict_proba(x[valid])[:, 1]
    prediction = model.predict(x[valid])
    precision = float(precision_score(y[valid], prediction, zero_division=0))
    recall = float(recall_score(y[valid], prediction, zero_division=0))
    f1 = float(f1_score(y[valid], prediction, zero_division=0))
    tn, fp, fn, tp = [int(v) for v in confusion_matrix(y[valid], prediction, labels=[0, 1]).ravel()]
    order = np.argsort(-probability)
    rows = [{"segment_id": str(records[int(valid[j])].get("segment_id", f"row-{int(valid[j])+1}")), "risk_pct": round(float(probability[j]) * 100, 1), "triage": "优先听漏复核" if prediction[j] else "常规巡查", "actual": "已确认漏点" if y[valid[j]] else "已确认正常"} for j in order]
    important = int(np.argmax(model.feature_importances_))
    first_rule = export_text(model, feature_names=FEATURES).splitlines()[0].strip()
    return {
        "summary": f"{len(train)}段训练、{len(valid)}段独立验证；实际树深{model.get_depth()}，生成{model.get_n_leaves()}个可复核叶节点。",
        "metrics": [{"label": "验证F1", "value": round(f1, 4)}, {"label": "漏点召回率", "value": round(recall * 100, 2), "unit": "%"}, {"label": "分诊精确率", "value": round(precision * 100, 2), "unit": "%"}, {"label": "验证漏检", "value": fn, "unit": "段"}],
        "table": {"columns": [{"key": "segment_id", "label": "管段"}, {"key": "risk_pct", "label": "叶节点漏点率(%)"}, {"key": "triage", "label": "分诊建议"}, {"key": "actual", "label": "留出集复核结果"}], "rows": rows},
        "chart": {"type": "bar", "labels": LABELS, "series": [{"name": "Gini分裂重要性", "values": [round(float(v), 4) for v in model.feature_importances_]}]},
        "findings": [f"验证混淆矩阵：命中漏点{tp}、误报{fp}、漏检{fn}、正确排除{tn}。", f"模型最重视{LABELS[important]}；根节点规则：{first_rule}。", "调高树深可能拟合局部噪声；只依据留出F1和漏检率选择规则复杂度。"],
        "method": metadata()["method"], "warnings": ["分诊规则仅辅助现场巡检，不作为自动停水或施工决策。"],
    }
