/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string,revision:number,parent_dataset_id:number|null,merge:Object|null}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{segment_id:string,action:'added'|'replaced'|'ignored',version:number,current_version:number|null,reason:string}} RevisionDetail */
/** @typedef {{created:boolean,message:string,summary:Object,details:RevisionDetail[],base:Object,dataset:Dataset}} RevisionResult */
export {};
