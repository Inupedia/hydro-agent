from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from hydro_agent.models.xaj.contracts import XajScheme
from hydro_agent.models.xaj.upstream import MODEL_SHA256, MODEL_VERSION

VENDOR = Path(__file__).resolve().parents[1] / 'models/xaj/vendor'
STAGES = (
    ('M01_CHECK_MATERIALS', '检查地形与站点资料'),
    ('M02_DELINEATE', '提取流域与计算单元'),
    ('M03_REVIEW_BOUNDARY', '复核出口与流域边界'),
    ('M04_BUILD_INPUTS', '构建面雨量与模型输入'),
    ('M05_VALIDATE_PLAN', '校验并保存完整方案'),
)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    resolution_m: float = Field(default=90, ge=30, le=1000)
    stream_area_km2: float = Field(default=50, gt=0, le=10000)
    unit_area_km2: float = Field(default=50, gt=0, le=10000)
    warmup_days: int = Field(default=365, ge=1, le=1000)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


class ModelPlanService:
    """One immutable build directory per configuration; explicit boundary review gate.

    Only bundled, checksum-verified teacher code executes. Material data is read
    from a configured local academy dataset, never arbitrary submitted scripts.
    """

    def __init__(self, root: Path, academy: Path):
        self.root, self.academy = Path(root).resolve(), Path(academy).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.RLock()
        for path in self.root.glob('plan-*/plan.json'):
            p = json.loads(path.read_text(encoding='utf-8'))
            if p['status'] in ('running', 'queued'):
                p.update(status='failed', error='服务重启中断了建模，请新建方案；未复用不完整成果。')
                write_json(path, p)

    def directory(self, plan_id: str) -> Path:
        if not re.fullmatch(r'plan-[a-f0-9]{12}', plan_id):
            raise ValueError('invalid model plan id')
        return self.root / plan_id

    def get(self, plan_id: str) -> dict:
        with self.lock:
            path = self.directory(plan_id) / 'plan.json'
            if not path.is_file():
                raise KeyError(plan_id)
            return json.loads(path.read_text(encoding='utf-8'))

    def list(self) -> list[dict]:
        return [self.get(p.parent.name) for p in sorted(self.root.glob('plan-*/plan.json'), reverse=True)]

    def _update(self, plan_id, **fields):
        with self.lock:
            plan = self.get(plan_id)
            plan.update(fields)
            write_json(self.directory(plan_id) / 'plan.json', plan)
            return plan

    def _stage(self, plan_id, code, status, detail=''):
        with self.lock:
            plan = self.get(plan_id)
            for stage in plan['stages']:
                if stage['code'] == code:
                    stage.update(status=status, detail=detail)
            plan['current_stage'] = code
            write_json(self.directory(plan_id) / 'plan.json', plan)

    def create(self, request: PlanRequest) -> dict:
        plan_id = f'plan-{uuid.uuid4().hex[:12]}'
        with self.lock:
            self.directory(plan_id).mkdir()
            payload = dict(plan_id=plan_id, basin_id='yaogu', model_mode='lumped',
                           status='queued', error=None, config=request.model_dump(),
                           model_version=MODEL_VERSION, model_source_sha256=MODEL_SHA256,
                           stages=[dict(code=code, label=label, status='pending', detail='') for code,label in STAGES])
            write_json(self.directory(plan_id) / 'plan.json', payload)
        self.pool.submit(self._build, plan_id, False)
        return payload

    def confirm(self, plan_id: str, boundary_hash: str) -> dict:
        with self.lock:
            p = self.get(plan_id)
            if p['status'] != 'awaiting_review':
                raise ValueError('方案当前不在边界复核阶段')
            if boundary_hash != p['boundary_hash']:
                raise ValueError('边界版本已变化，请重新查看地图')
            self._verify_files(plan_id, p['review_files'])
            self._stage(plan_id, 'M03_REVIEW_BOUNDARY', 'completed', '已确认当前出口、边界及面积')
            self._update(plan_id, status='queued', boundary_reviewed=True)
            self.pool.submit(self._build, plan_id, True)
            return self.get(plan_id)

    def _command(self, plan_id, *args):
        root = self.directory(plan_id)
        # Copy trusted scripts into each plan: teacher plotting caches never
        # mutate the installed package or the user's supplied academy.
        code = root / 'builder'
        env = os.environ.copy()
        for key in ('PROJ_LIB', 'PROJ_DATA', 'GDAL_DATA'):
            env.pop(key, None)
        env['MPLCONFIGDIR'] = str(root / 'plot-cache')
        with (root / 'build.log').open('a', encoding='utf-8') as log:
            result = subprocess.run([sys.executable, str(code / 'dem_xaj_lab.py'), *map(str, args)],
                                    cwd=code, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=900, check=False)
        if result.returncode:
            tail = (root / 'build.log').read_text(encoding='utf-8')[-1800:]
            raise ValueError(f'建模工具失败：{tail}')

    def _build(self, plan_id, reviewed):
        root = self.directory(plan_id)
        try:
            p = self._update(plan_id, status='running', error=None)
            cfg = p['config']
            if not reviewed:
                self._stage(plan_id, 'M01_CHECK_MATERIALS', 'running')
                files = json.loads((VENDOR / 'build_provenance.json').read_text(encoding='utf-8'))
                (root / 'builder').mkdir()
                for name, expected in files.items():
                    if digest(VENDOR / name) != expected:
                        raise ValueError('老师建模源码校验失败')
                    shutil.copy2(VENDOR / name, root / 'builder' / name)
                for relative in ('examples/data/ST_STNM.xlsx', 'examples/dem/yaogu/sources.json'):
                    if not (self.academy / relative).is_file():
                        raise ValueError(f'缺少资料：{relative}')
                material_files = {str(f.relative_to(self.academy)): digest(f)
                                  for f in (self.academy/'examples/data').rglob('*')
                                  if f.is_file() and f.suffix.lower() in ('.csv','.xlsx','.shp','.shx','.dbf','.prj','.cpg')}
                self._update(plan_id, material_files=material_files)
                self._stage(plan_id, 'M01_CHECK_MATERIALS', 'completed')
                self._stage(plan_id, 'M02_DELINEATE', 'running')
                self._command(plan_id, 'delineate', '--raw', self.academy/'examples/data',
                              '--dem', self.academy/'examples/dem/yaogu', '--case-dir', root/'case',
                              '--resolution', cfg['resolution_m'], '--stream-area-km2', cfg['stream_area_km2'],
                              '--unit-area-km2', cfg['unit_area_km2'], '--model-mode', 'lumped')
                boundary = json.loads((root/'case/gis/boundary_check.json').read_text(encoding='utf-8'))
                if not boundary['accepted']:
                    raise ValueError('边界未通过数值检查')
                review = {str(f.relative_to(root)): digest(f) for f in (root/'case/gis').rglob('*') if f.is_file()}
                review['case/dem_config.json'] = digest(root/'case/dem_config.json')
                boundary_hash = hashlib.sha256(json.dumps(review, sort_keys=True).encode()).hexdigest()
                self._stage(plan_id, 'M02_DELINEATE', 'completed')
                self._stage(plan_id, 'M03_REVIEW_BOUNDARY', 'awaiting_review', '请核对地图上的出口、边界与面积')
                self._update(plan_id, status='awaiting_review', boundary=boundary,
                             boundary_hash=boundary_hash, review_files=review)
                return
            self._verify_files(plan_id, p['review_files'])
            for relative, expected in p['material_files'].items():
                if digest(self.academy/relative) != expected:
                    raise ValueError('站点或原始资料已改变，请重新建模并复核地图')
            self._stage(plan_id, 'M04_BUILD_INPUTS', 'running')
            self._command(plan_id, 'build', '--prepare-only', '--raw', self.academy/'examples/data',
                          '--case-dir', root/'case')
            self._stage(plan_id, 'M04_BUILD_INPUTS', 'completed')
            self._stage(plan_id, 'M05_VALIDATE_PLAN', 'running')
            self._normalize(plan_id)
            files = {str(f.relative_to(root)): digest(f) for folder in ('case', 'normalized')
                     for f in (root/folder).rglob('*') if f.is_file()}
            files['scheme.json'] = digest(root/'scheme.json')
            content_hash = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
            self._stage(plan_id, 'M05_VALIDATE_PLAN', 'completed')
            self._update(plan_id, status='ready', files=files, content_hash=content_hash)
        except Exception as exc:
            p = self.get(plan_id)
            if p.get('current_stage'):
                self._stage(plan_id, p['current_stage'], 'failed', str(exc))
            self._update(plan_id, status='failed', error=str(exc))

    def _normalize(self, plan_id):
        root = self.directory(plan_id)
        case = root/'case'
        def rows(relative):
            with (case/relative).open(encoding='utf-8', newline='') as f:
                return list(csv.DictReader(f))
        units = rows('gis/units.csv')
        if len(units) != 1:
            raise ValueError('当前预报适配器仅接受集总方案，不能静默合并分区输出')
        params = rows('parameters/parameters.csv')
        if len(params) != 1:
            raise ValueError('参数数量与计算单元不一致')
        raw = {k:float(v) for k,v in params[0].items()}
        mapping = dict(K='kc', B='b', IM='imp', UM='wum', LM='wlm', C='c', SM='sm', EX='ex',
                       KI='ki', KG='kg', CS='cs', L='lag', CI='ci', CG='cg')
        p = {k:raw[v] for k,v in mapping.items()}
        p['DM'] = raw['wm']-raw['wum']-raw['wlm']
        scheme = XajScheme(warmup_days=self.get(plan_id)['config']['warmup_days'], parameters=p,
                           routing=dict(dp=int(raw['dp']), ke=raw['ke'], xe=raw['xe']))
        rain, evap, obs = (rows(f'model_inputs/{name}.csv') for name in
                           ('precipitation_mm', 'evaporation_mm', 'observed'))
        if [r['time'] for r in rain] != [r['time'] for r in evap] or [r['time'] for r in rain] != [r['time'] for r in obs]:
            raise ValueError('雨量、蒸发和观测日期未对齐')
        dates = [date.fromisoformat(r['time'][:10]) for r in rain]
        if any(b-a != timedelta(days=1) for a,b in zip(dates,dates[1:])):
            raise ValueError('输入日期不连续')
        norm = root/'normalized'
        norm.mkdir()
        for name, data in [('forcing', rain), ('flow', obs)]:
            with (norm/f'{name}.jsonl').open('w', encoding='utf-8') as out:
                for i, row in enumerate(data):
                    available = datetime.combine(dates[i]+timedelta(days=1), time(8), ZoneInfo('Asia/Shanghai'))
                    item = dict(valid_date=str(dates[i]), available_at=available.isoformat(), source='teacher-yaogu-daily')
                    if name == 'forcing':
                        item.update(precipitation_mm_day=float(row['unit_1']), pet_mm_day=float(evap[i]['unit_1']), source_kind='observation')
                    else:
                        item['discharge_m3s'] = float(row['discharge'])
                    out.write(json.dumps(item, allow_nan=False)+'\n')
        write_json(norm/'basin.json', dict(basin_id='yaogu', area_km2=float(units[0]['area_km2']),
                    day_timezone='Asia/Shanghai', model_plan_id=plan_id,
                    evaporation_kind='measured evaporation; legacy pet_mm_day field; native KC conversion',
                    time_semantics='teacher daily labels retained; 08:00; retrospective R only'))
        from hydro_agent.data.lowman import load_normalized_source
        load_normalized_source(norm)  # Reject missing, nonfinite or negative inputs.
        write_json(root/'scheme.json', {**scheme.model_dump(), 'model_version':MODEL_VERSION, 'model_plan_id':plan_id})
        self._update(plan_id, area_km2=float(units[0]['area_km2']), unit_count=1,
                     data_start=str(dates[0]), data_end=str(dates[-1]),
                     suggested_start=str(dates[0]+timedelta(days=max(60,scheme.warmup_days)+70)),
                     suggested_end=str(dates[0]+timedelta(days=max(60,scheme.warmup_days)+72)))

    def _verify_files(self, plan_id, files):
        root = self.directory(plan_id)
        for relative, expected in files.items():
            path = (root/relative).resolve()
            if not path.is_relative_to(root) or not path.is_file() or digest(path) != expected:
                raise ValueError(f'方案文件已变化或缺失：{relative}；请重新建模，旧结果不可复用')

    def require_ready(self, plan_id):
        p = self.get(plan_id)
        if p['status'] != 'ready' or not p.get('boundary_reviewed'):
            raise ValueError('模型方案尚未完成建模、边界复核和输入校验')
        self._verify_files(plan_id, p['files'])
        return p
