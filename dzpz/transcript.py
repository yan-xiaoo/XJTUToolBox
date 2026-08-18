from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import requests

from auth import ServerError


WORKFLOW_MAP = {
    "在校本科生": 29,
    "研究生": 34,
    "已毕业本科(校友)": 46,
    "研究生校友": 49,
}
BASE = "https://dzpz.xjtu.edu.cn"
REFERER = f"{BASE}/spa/workflow/static4form/index.html"


@dataclass
class TranscriptType:
    name: str
    value: int


@dataclass
class FormContext:
    workflow_id: int
    params: dict
    submit_params: dict
    maindata: dict
    type_options: list[TranscriptType]
    linkage_uuid: str
    signature_attributes: str
    signature_secret: str
    default_date: str
    default_request_name: str


@dataclass
class LinkageResult:
    student_id: str
    enroll_year: str
    template_path: str
    category_name: str
    workflow_id_field: str


@dataclass
class SubmitResult:
    request_id: int
    session_key: str
    submit_token: int


@dataclass
class DownloadInfo:
    filename: str
    download_url: str
    filesize: str = ""


class Transcript:
    def __init__(self, session: requests.Session):
        self.session = session

    @property
    def user_id(self) -> str:
        user_id = getattr(self.session, "user_id", "") or self.session.headers.get("X-DZPZ-User-Id", "")
        if not user_id:
            raise ServerError(102, "电子成绩单未登录")
        return user_id

    def _post(self, path: str, data: dict[str, Any]) -> requests.Response:
        return self.session.post(
            f"{BASE}{path}",
            data=data,
            headers={"Referer": REFERER, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )

    def _json(self, response: requests.Response) -> dict:
        try:
            return response.json()
        except ValueError as exc:
            raise ServerError(1, "电子成绩单接口返回了无法解析的数据") from exc

    def _field_value(self, maindata: dict, name: str) -> str:
        field = maindata.get(name) or {}
        if isinstance(field, dict):
            return str(field.get("value") or "")
        return str(field or "")

    def load_create_form(self, workflow_id: int) -> FormContext:
        payload = self._json(self._post("/api/workflow/reqform/loadForm", {
            "beagenter": "0",
            "isagent": "0",
            "iscreate": "1",
            "workflowid": str(workflow_id),
        }))
        params = payload.get("params") or {}
        submit_params = payload.get("submitParams") or {}
        maindata = payload.get("maindata") or {}
        options = []
        items = ((((payload.get("tableInfo") or {}).get("main") or {}).get("fieldinfomap") or {}).get("7243") or {})
        select_items = ((items.get("selectattr") or {}).get("selectitemlist") or [])
        for item in select_items:
            if item.get("cancel") == 1:
                continue
            options.append(TranscriptType(str(item.get("selectname") or ""), int(item.get("selectvalue") or 0)))
        return FormContext(
            workflow_id=workflow_id,
            params=params,
            submit_params=submit_params,
            maindata=maindata,
            type_options=options,
            linkage_uuid=str(params.get("linkageUUID") or ""),
            signature_attributes=str(params.get("signatureAttributesStr") or ""),
            signature_secret=str(params.get("signatureSecretKey") or ""),
            default_date=self._field_value(maindata, "field7249") or date.today().isoformat(),
            default_request_name=self._field_value(maindata, "field-1"),
        )

    def get_linkage_data(self, ctx: FormContext, type_value: int) -> LinkageResult:
        first = self._json(self._post("/api/workflow/linkage/reqDataInputResult", {
            "requestid": "-1",
            "workflowid": str(ctx.workflow_id),
            "nodeid": "49",
            "formid": "-14",
            "isbill": "1",
            "triSource": "2",
            "showAI": "0",
            "triFieldid_43": "7243",
            "rowIndexStr_43": "-1",
            "triTableMark_43": "main",
            "field7243": "",
            "triFieldid_64": "7250",
            "rowIndexStr_64": "-1",
            "triTableMark_64": "main",
            "field7250": self.user_id,
            "linkageid": "43,64",
            "linkageUUID": ctx.linkage_uuid,
            "wfTestStr": "",
            "f_weaver_belongto_userid": self.user_id,
            "f_weaver_belongto_usertype": "0",
        }))
        assign64 = ((first.get("assignInfo_64") or {}).get("changeValue") or {})
        second = self._json(self._post("/api/workflow/linkage/reqDataInputResult", {
            "requestid": "-1",
            "workflowid": str(ctx.workflow_id),
            "nodeid": "49",
            "formid": "-14",
            "isbill": "1",
            "triSource": "1",
            "showAI": "0",
            "triFieldid_43": "7243",
            "rowIndexStr_43": "-1",
            "triTableMark_43": "main",
            "field7243": str(type_value),
            "linkageid": "43",
            "linkageUUID": ctx.linkage_uuid,
            "wfTestStr": "",
            "f_weaver_belongto_userid": self.user_id,
            "f_weaver_belongto_usertype": "0",
        }))
        assign43 = ((second.get("assignInfo_43") or {}).get("changeValue") or {})
        return LinkageResult(
            student_id=str((assign64.get("field7237") or {}).get("value") or ""),
            enroll_year=str((assign64.get("field7536") or {}).get("value") or ""),
            template_path=str((assign43.get("field7247") or {}).get("value") or ""),
            category_name=str((assign43.get("field7241") or {}).get("value") or ""),
            workflow_id_field=str(ctx.workflow_id),
        )

    def generate_preview_pdf(self, workflow_id: int, type_value: int) -> str:
        response = self._post("/api/xjtuapi/procfiles", {
            "reqid": "-1",
            "wfid": str(workflow_id),
            "uid": self.user_id,
            "fjmc": "dzcjdyl",
            "cjdwj": "",
            "sfybc": "0",
            "cjdlx": str(type_value),
        })
        doc_id = response.text.strip()
        if not doc_id:
            raise ServerError(1, "生成成绩单失败：服务器无响应")
        return doc_id

    def submit_create(self, ctx: FormContext, linkage: LinkageResult, type_value: int, doc_id: str) -> SubmitResult:
        token_key = f"{self.user_id}_{ctx.workflow_id}_addrequest_submit_token"
        token = ctx.submit_params.get(token_key) or int(date.today().strftime("%Y%m%d"))
        payload = self._json(self._post("/api/workflow/reqform/requestOperation", {
            "formid": "-14",
            "f_weaver_belongto_userid": self.user_id,
            "isWorkflowDoc": "false",
            "f_weaver_belongto_usertype": "0",
            "nodetype": "0",
            "src": "save",
            token_key: str(token),
            "workflowtype": "26",
            "iscreate": "1",
            "requestid": "-1",
            "linkageUUID": ctx.linkage_uuid,
            "lastloginuserid": self.user_id,
            "nodeid": "49",
            "workflowid": str(ctx.workflow_id),
            "isbill": "1",
            "isOdocRequest": "0",
            "actiontype": "requestOperation",
            "closePage": "false",
            "type": "save",
            "existChangeRange": "field7536,field7237,field7245,field7243,field7247,field7241,field7244,field7501",
            "field7249": ctx.default_date,
            "field7501": "1",
            "requestname": ctx.default_request_name,
            "requestlevel": "0",
            "field7240": "西安交通大学",
            "field7250": self.user_id,
            "field7246": self.user_id,
            "field7243": str(type_value),
            "field-10": "",
            "field7237": linkage.student_id,
            "field7239": "",
            "field7238": "",
            "field7502": "",
            "field7536": linkage.enroll_year,
            "field7244": doc_id,
            "field7241": linkage.category_name,
            "field7504": "",
            "field7247": linkage.template_path,
            "field7245": linkage.workflow_id_field,
            "mainFieldUnEmptyCount": "12",
            "detailFieldUnEmptyCount": "0",
            "signatureAttributesStr": ctx.signature_attributes,
            "signatureSecretKey": ctx.signature_secret,
            "selectNextFlow": "0",
            "openDataVerify": "0",
            "wfTestStr": "",
        }))
        data = payload.get("data") or {}
        if data.get("type") != "SUCCESS":
            raise ServerError(1, payload.get("message") or data.get("type") or "提交失败")
        info = data.get("resultInfo") or {}
        submit = data.get("submitParams") or {}
        return SubmitResult(
            request_id=int(info.get("requestid")),
            session_key=str(info.get("sessionkey") or ""),
            submit_token=int(submit.get(token_key) or token),
        )

    def reload_and_forward(self, ctx: FormContext, first: SubmitResult, type_value: int) -> SubmitResult:
        load = self._json(self._post("/api/workflow/reqform/loadForm", {
            "belongTest": "false",
            "f_weaver_belongto_userid": self.user_id,
            "f_weaver_belongto_usertype": "0",
            "isOpenContinuationProcess": "undefined",
            "isaffirmance": "0",
            "needRemind": "false",
            "requestid": str(first.request_id),
            "saveType": "undefined",
            "selectNextFlow": "0",
            "sessionkey": first.session_key,
        }))
        params = load.get("params") or {}
        submit_params = load.get("submitParams") or {}
        maindata = load.get("maindata") or {}
        self._post("/api/xjtuapi/checksubmit", {
            "reqid": str(first.request_id),
            "wfid": str(ctx.workflow_id),
            "uid": self.user_id,
            "sqrq": ctx.default_date,
            "cjdlx": str(type_value),
        })
        submit_token_key = f"{self.user_id}_{first.request_id}_request_submit_token"
        add_token_key = f"{self.user_id}_{ctx.workflow_id}_addrequest_submit_token"
        submit = self._json(self._post("/api/workflow/reqform/requestOperation", {
            "formid": "-14",
            "iscreate": "0",
            "creatertype": "0",
            "isdialog": "1",
            submit_token_key: str(submit_params.get(submit_token_key) or first.submit_token),
            "lastOperateDate": str(params.get("lastOperateDate") or ctx.default_date),
            "nodeid": "49",
            "workflowid": str(ctx.workflow_id),
            "isbill": "1",
            "authStr": str(params.get("authStr") or ""),
            "f_weaver_belongto_userid": self.user_id,
            "currenttime": str(params.get("lastOperateTime") or ""),
            "f_weaver_belongto_usertype": "0",
            "agentorByAgentId": "-1",
            "lastOperateTime": str(params.get("lastOperateTime") or ""),
            "requestid": str(first.request_id),
            "isremark": "0",
            "creater": self.user_id,
            "isCptwf": "false",
            "agentType": "0",
            "authSignatureStr": str(params.get("authSignatureStr") or ""),
            "nodetype": "0",
            "lastOperator": self.user_id,
            add_token_key: str(submit_params.get(add_token_key) or first.submit_token),
            "isFormSignature": "0",
            "linkageUUID": str(params.get("linkageUUID") or ""),
            "billid": str(params.get("billid") or ""),
            "src": "submit",
            "takisremark": "0",
            "workflowtype": "26",
            "needwfback": "0",
            "isOdocRequest": "0",
            "verifyRequiredRange": "field-9999,field7243,",
            "actiontype": "requestOperation",
            "isFirstSubmit": "0",
            "existChangeRange": "",
            "field7249": self._field_value(maindata, "field7249"),
            "field7502": self._field_value(maindata, "field7502"),
            "field7248": self._field_value(maindata, "field7248"),
            "field7501": self._field_value(maindata, "field7501"),
            "field7247": self._field_value(maindata, "field7247"),
            "field7505": self._field_value(maindata, "field7505"),
            "field7504": self._field_value(maindata, "field7504"),
            "field7242": self._field_value(maindata, "field7242"),
            "field7241": self._field_value(maindata, "field7241"),
            "field7240": self._field_value(maindata, "field7240"),
            "field-9": self._field_value(maindata, "field-9"),
            "field7246": self._field_value(maindata, "field7246"),
            "field7245": self._field_value(maindata, "field7245"),
            "field7564": self._field_value(maindata, "field7564"),
            "field7244": self._field_value(maindata, "field7244"),
            "field7243": self._field_value(maindata, "field7243"),
            "field7239": self._field_value(maindata, "field7239"),
            "field7536": self._field_value(maindata, "field7536"),
            "field7238": self._field_value(maindata, "field7238"),
            "field7237": self._field_value(maindata, "field7237"),
            "field7250": self._field_value(maindata, "field7250"),
            "requestname": self._field_value(maindata, "field-1"),
            "requestlevel": "0",
            "field-10": "",
            "chatsType": "-1",
            "messageType": "-1",
            "mainFieldUnEmptyCount": "12",
            "detailFieldUnEmptyCount": "0",
            "signatureAttributesStr": str(params.get("signatureAttributesStr") or ""),
            "signatureSecretKey": str(params.get("signatureSecretKey") or ""),
            "selectNextFlow": "0",
            "openDataVerify": "0",
            "wfTestStr": "",
        }))
        data = submit.get("data") or {}
        if data.get("type") != "SUCCESS":
            message = ((data.get("messageInfo") or {}).get("message") or submit.get("message") or "转发失败")
            raise ServerError(1, str(message))
        info = data.get("resultInfo") or data.get("messageInfo") or {}
        return SubmitResult(
            request_id=first.request_id,
            session_key=str(info.get("sessionkey") or first.session_key),
            submit_token=int((data.get("submitParams") or {}).get(submit_token_key) or first.submit_token),
        )

    def get_download_info(self, second: SubmitResult) -> DownloadInfo:
        payload = self._json(self._post("/api/workflow/reqform/loadForm", {
            "belongTest": "false",
            "f_weaver_belongto_userid": self.user_id,
            "f_weaver_belongto_usertype": "0",
            "isOpenContinuationProcess": "undefined",
            "isRefresh": "1",
            "isShowChart": "3",
            "isaffirmance": "0",
            "needRemind": "false",
            "requestid": str(second.request_id),
            "saveType": "undefined",
            "sessionkey": second.session_key,
        }))
        maindata = payload.get("maindata") or {}
        files = (((maindata.get("field7564") or {}).get("specialobj") or {}).get("filedatas") or [])
        if files:
            item = files[0]
            link = str(item.get("loadlink") or "")
            if link and not link.startswith("http"):
                link = BASE + link
            return DownloadInfo(str(item.get("filename") or "成绩单.pdf"), link, str(item.get("filesize") or ""))
        doc_id = self._field_value(maindata, "field7244")
        if not doc_id:
            raise ServerError(1, "无法获取下载链接：成绩单文件尚未生成")
        params = payload.get("params") or {}
        url = (
            f"{BASE}/weaver/weaver.file.FileDownload?fileid={doc_id}&download=1"
            f"&requestid={second.request_id}&desrequestid=0"
            f"&authStr={params.get('authStr') or ''}&authSignatureStr={params.get('authSignatureStr') or ''}"
            f"&f_weaver_belongto_userid={self.user_id}&f_weaver_belongto_usertype=0&fromrequest=1"
        )
        return DownloadInfo("成绩单.pdf", url)

    def download_pdf(self, url: str) -> bytes:
        response = self.session.get(url, headers={"Referer": REFERER}, timeout=60)
        if response.status_code != 200 or not response.content:
            raise ServerError(1, f"下载失败：HTTP {response.status_code}")
        return response.content

    def generate_and_download(self, workflow_id: int, type_value: int) -> tuple[DownloadInfo, bytes]:
        ctx = self.load_create_form(workflow_id)
        linkage = self.get_linkage_data(ctx, type_value)
        doc_id = self.generate_preview_pdf(workflow_id, type_value)
        first = self.submit_create(ctx, linkage, type_value, doc_id)
        second = self.reload_and_forward(ctx, first, type_value)
        info = self.get_download_info(second)
        return info, self.download_pdf(info.download_url)
