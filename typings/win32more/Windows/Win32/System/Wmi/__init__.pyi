# Consumed WMI calls: connecting to a namespace, a forward-only WQL query, reading and
# writing a property, and running a method with spawned in-parameters. HRESULT is a
# signed integer; Workspace passes no context, call result or out-parameters.
import ctypes

from win32more._win32 import ComPtr, Guid
from win32more.Windows.Win32.System.Variant import VARIANT

WBEM_FLAG_FORWARD_ONLY: int
WBEM_FLAG_RETURN_IMMEDIATELY: int
WBEM_INFINITE: int
WbemLocator: Guid

class IWbemClassObject(ComPtr):
    def Get(self, name: str, flags: int, value: VARIANT, type: None, flavor: None) -> int: ...
    def Put(self, name: str, flags: int, value: VARIANT, type: int) -> int: ...
    def SpawnInstance(self, flags: int, instance: IWbemClassObject) -> int: ...
    def GetMethod(self, name: str, flags: int, in_signature: IWbemClassObject, out_signature: None) -> int: ...

class IEnumWbemClassObject(ComPtr):
    def Next(self, timeout: int, count: int, objects: IWbemClassObject, returned: ctypes.c_uint32) -> int: ...

class IWbemServices(ComPtr):
    def GetObject(self, path: str, flags: int, context: None, result: IWbemClassObject, call_result: None) -> int: ...
    def ExecQuery(self, language: str, query: str, flags: int, context: None, result: IEnumWbemClassObject) -> int: ...
    def ExecMethod(self, path: str, method: str, flags: int, context: None, arguments: IWbemClassObject, out: None, call_result: None) -> int: ...

class IWbemLocator(ComPtr):
    def ConnectServer(
        self,
        resource: str,
        user: None,
        password: None,
        locale: None,
        flags: int,
        authority: None,
        context: None,
        services: IWbemServices,
    ) -> int: ...
