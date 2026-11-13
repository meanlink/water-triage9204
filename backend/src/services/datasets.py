import math
import time

from fastapi import HTTPException
from sqlalchemy import select

from src.models import Dataset
from src.services.business import FEATURES, metadata
from src.utils.serialization import checksum

# 每条管段记录都带一个版本号。补传更正按管段取最高版本，旧版本晚到只忽略不覆盖。
VERSION_KEY = 'segment_version'
LABEL_KEYS = list(FEATURES) + ['confirmed_leak']


def _column_labels():
    return {c['key']: c['label'] for c in metadata()['columns']}


def _read_version(value, index):
    if value is None or value == '':
        return 1
    if isinstance(value, bool):
        raise HTTPException(422, f'第 {index+1} 行 管段版本必须为大于等于1的整数')
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(422, f'第 {index+1} 行 管段版本必须为大于等于1的整数')
    if not math.isfinite(number) or number != int(number) or not 1 <= number <= 1000000000:
        raise HTTPException(422, f'第 {index+1} 行 管段版本必须为大于等于1的整数')
    return int(number)


def _normalize_row(row, index):
    """校验并规范化一行管段记录，返回新字典，不修改调用方数据。"""
    result = dict(row)
    labels = _column_labels()
    for column in metadata()['columns']:
        key = column['key']
        value = row.get(key)
        if value is None or value == '':
            if column.get('optional'):
                result[key] = column.get('default')
                continue
            raise HTTPException(422, f'第 {index+1} 行缺少字段 {labels[key]}')
        if column['type'] == 'number' and not column.get('optional'):
            try:
                if isinstance(value, bool) or not math.isfinite(float(value)):
                    raise ValueError()
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                raise HTTPException(422, f'第 {index+1} 行 {labels[key]} 必须为有限数值')
            if number < 0:
                raise HTTPException(422, f'第 {index+1} 行 {labels[key]} 必须为非负有限数值')
            result[key] = number
    if result.get('segment_id') is None:
        raise HTTPException(422, f'第 {index+1} 行缺少字段 {labels["segment_id"]}')
    label = result['confirmed_leak']
    if label not in (0.0, 1.0):
        raise HTTPException(422, f'第 {index+1} 行 复核漏点(1/0) 只能为0或1')
    result['confirmed_leak'] = int(label)
    result['segment_id'] = str(result['segment_id']).strip()
    version = _read_version(row.get(VERSION_KEY), index)
    result[VERSION_KEY] = version
    return result


def _content(row):
    return tuple(float(row[key]) for key in LABEL_KEYS)


def _diff_fields(left, right):
    labels = _column_labels()
    return [{'key': key, 'label': labels[key], 'from': float(left[key]), 'to': float(right[key])}
            for key in LABEL_KEYS if float(left[key]) != float(right[key])]


def _normalize_records(records, allow_repeats=False):
    normalized = []
    seen = {}
    for index, row in enumerate(records):
        item = _normalize_row(row, index)
        segment_id = item['segment_id']
        if not segment_id:
            raise HTTPException(422, f'第 {index+1} 行 管段编号不能为空')
        if len(segment_id) > 80:
            raise HTTPException(422, f'第 {index+1} 行 管段编号过长')
        if not allow_repeats and segment_id in seen:
            raise HTTPException(422, f'第 {index+1} 行 管段编号 {segment_id} 与第 {seen[segment_id]+1} 行重复')
        seen.setdefault(segment_id, index)
        normalized.append(item)
    return normalized


def _unique_name(db, base):
    stem = f'{base.name} · 补传更正 r{(base.revision or 1) + 1}'
    stem = stem[:150]
    candidate = stem
    counter = 2
    while db.scalar(select(Dataset).where(Dataset.name == candidate)):
        candidate = f'{stem} ({counter})'[:160]
        counter += 1
        if counter > 100:
            raise HTTPException(409, '自动批次名冲突过多，请显式填写批次名称')
    return candidate


def create(db, data):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(Dataset).where(Dataset.name == name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    records = _normalize_records(data.records)
    d = Dataset(name=name, source=data.source, records=records, checksum=checksum(records), revision=1, created_at=time.time())
    db.add(d)
    db.flush()
    return d


def _base_rows(rows):
    """读取原批次记录；历史数据可能没有 segment_version，视作 v1。"""
    normalized = []
    for index, row in enumerate(rows):
        item = dict(row)
        if item.get('segment_version') is None or item.get('segment_version') == '':
            item['segment_version'] = 1
        try:
            normalized.append(_normalize_row(item, index))
        except HTTPException as exc:
            raise HTTPException(409, f'原批次第 {index+1} 行无法参与合并：{exc.detail}') from exc
    return normalized


def revision(db, dataset_id, data):
    base = db.get(Dataset, dataset_id)
    if not base:
        raise HTTPException(404, '数据批次不存在')
    incoming = _normalize_records(data.records, allow_repeats=True)
    if data.name is not None and data.name.strip():
        name = data.name.strip()
        if len(name) < 2:
            raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
        if db.scalar(select(Dataset).where(Dataset.name == name)):
            raise HTTPException(409, '该数据批次名已存在，请修改名称')
    else:
        name = _unique_name(db, base)

    state = {}
    base_order = []
    for index, result in enumerate(_base_rows(base.records)):
        segment_id = result['segment_id']
        if not segment_id:
            raise HTTPException(409, f'原批次第 {index+1} 行缺少管段编号，无法按管段合并')
        if segment_id in state:
            raise HTTPException(409, f'原批次存在重复管段 {segment_id}，无法按管段合并，请先整理原批次')
        state[segment_id] = {'row': result, 'version': result[VERSION_KEY]}
        base_order.append(segment_id)

    base_ids = set(base_order)
    added_ids = []
    replaced_ids = set()
    details = []
    conflicts = []
    ignored = 0

    for row in incoming:
        segment_id = row['segment_id']
        version = row[VERSION_KEY]
        current = state.get(segment_id)
        if current is None:
            # 原批次没有该管段：作为新增样本，后续同管段的更高版本仍会在此状态上比较。
            state[segment_id] = {'row': row, 'version': version}
            added_ids.append(segment_id)
            details.append({'segment_id': segment_id, 'action': 'added', 'version': version,
                            'current_version': None, 'reason': '原批次无此管段，作为新增样本纳入新批次'})
            continue
        if version < current['version']:
            ignored += 1
            details.append({'segment_id': segment_id, 'action': 'ignored', 'version': version,
                            'current_version': current['version'],
                            'reason': f'旧版本 v{version} 晚到，保留已采用的 v{current["version"]}，不覆盖'})
            continue
        if version == current['version']:
            if _content(row) == _content(current['row']):
                ignored += 1
                details.append({'segment_id': segment_id, 'action': 'ignored', 'version': version,
                                'current_version': current['version'],
                                'reason': '同版本内容一致，重复投递不新增样本'})
                continue
            conflicts.append({'segment_id': segment_id, 'version': version,
                              'current_version': current['version'],
                              'fields': _diff_fields(current['row'], row)})
            continue
        previous = current['version']
        current['row'] = row
        current['version'] = version
        if segment_id in base_ids:
            replaced_ids.add(segment_id)
            action = 'replaced'
            reason = f'版本 v{previous} → v{version}，按管段版本取新值'
        else:
            action = 'added'
            reason = f'同一补传内重复出现，采用更高版本 v{previous} → v{version}'
        details.append({'segment_id': segment_id, 'action': action, 'version': version,
                        'current_version': version, 'reason': reason})

    if conflicts:
        raise HTTPException(409, {
            'message': f'补传被整批拒绝：{len(conflicts)} 个管段在同版本下内容冲突',
            'conflicts': conflicts,
        })

    merged = [state[segment_id]['row'] for segment_id in base_order] + [state[segment_id]['row'] for segment_id in added_ids]
    summary = {
        'added': len(added_ids), 'replaced': len(replaced_ids), 'ignored': ignored,
        'unchanged': len(base_order) - len(replaced_ids),
        'before_rows': len(base_order), 'after_rows': len(merged),
    }
    if summary['added'] == 0 and summary['replaced'] == 0:
        return {'created': False, 'dataset': base, 'summary': summary, 'details': details, 'base': base,
                'message': '本次补传全部为重复投递或旧版本，未新增样本，也未生成新批次'}

    detail = {
        'base_dataset_id': base.id,
        'base_name': base.name,
        'base_revision': base.revision,
        'base_checksum': base.checksum,
        'summary': summary,
        'details': details,
        'created_at': time.time(),
    }
    d = Dataset(name=name, source=data.source or base.source, records=merged, checksum=checksum(merged),
                parent_dataset_id=base.id, revision=(base.revision or 1) + 1, merge_summary=detail, created_at=time.time())
    db.add(d)
    db.flush()
    return {'created': True, 'dataset': d, 'summary': summary, 'details': details, 'base': base}


def revision_response(payload):
    """把服务结果转成前端可直接渲染的结构（不含整批记录）。"""
    dataset = payload['dataset']
    base = payload['base']
    return {
        'created': payload['created'],
        'message': payload.get('message', ''),
        'summary': payload['summary'],
        'details': payload['details'],
        'base': {'id': base.id, 'name': base.name, 'revision': base.revision, 'checksum': base.checksum},
        'dataset': {
            'id': dataset.id, 'name': dataset.name, 'source': dataset.source,
            'rows': len(dataset.records), 'checksum': dataset.checksum,
            'revision': dataset.revision, 'parent_dataset_id': dataset.parent_dataset_id,
            'merge': payload['summary'], 'created_at': dataset.created_at,
        },
    }
