from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from src.config.database import get_db
from src.models import Dataset
from src.schemas.dataset import DatasetInput, DatasetRevisionInput
from src.middlewares.auth import current_user, can_write
from src.services import datasets
from src.services.audit import record
from src.utils.serialization import dataset_dict
router=APIRouter(prefix='/datasets')
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [dataset_dict(d) for d in db.scalars(select(Dataset).order_by(Dataset.id.desc()))]
@router.post('',status_code=201)
def create(data:DatasetInput,db=Depends(get_db),u=Depends(can_write)):
    d=datasets.create(db,data); record(db,u.email,'dataset.create',{'id':d.id,'rows':len(d.records),'revision':d.revision})
    db.commit(); return dataset_dict(d)
@router.post('/{id}/revisions')
def revise(id:int,data:DatasetRevisionInput,response:Response,db=Depends(get_db),u=Depends(can_write)):
    result=datasets.revision(db,id,data); payload=datasets.revision_response(result)
    record(db,u.email,'dataset.revision',{'base':id,'dataset':payload['dataset']['id'] if payload['created'] else None,
        'created':payload['created'],'summary':payload['summary'],'details':payload['details'][:200]})
    db.commit()
    response.status_code=201 if payload['created'] else 200
    return payload
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    d=db.get(Dataset,id)
    if not d:raise HTTPException(404,'数据批次不存在')
    return {**dataset_dict(d),'records':d.records,'merge':d.merge_summary}
