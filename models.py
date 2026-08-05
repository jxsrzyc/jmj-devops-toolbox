"""数据模型定义"""

class ServiceParam:
    """服务发版参数"""
    def __init__(self, id=None, business_module="", service_name="",
                 create_change_params="", run_devflow_params="", env="中国",
                 created_at=None, updated_at=None):
        self.id = id
        self.business_module = business_module
        self.service_name = service_name
        self.create_change_params = create_change_params
        self.run_devflow_params = run_devflow_params
        self.env = env
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}


class ServiceCredential:
    """服务凭证信息（扩展预留）"""
    def __init__(self, id=None, service_name="", access_url="",
                 username="", password="", internal_url="", external_url="",
                 notes="", created_at=None, updated_at=None):
        self.id = id
        self.service_name = service_name
        self.access_url = access_url
        self.username = username
        self.password = password
        self.internal_url = internal_url
        self.external_url = external_url
        self.notes = notes
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items()}
