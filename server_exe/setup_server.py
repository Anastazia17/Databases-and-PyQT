import sys
from cx_Freeze import setup, Executable

build_exe_options = {
    "packages": ["common", "logs", "server", "unit_tests"],
}
setup(
    name="mess_server_oct",
    version="0.0.1",
    description="mess_server_oct",
    options={
        "build_exe": build_exe_options
    },
    executables=[Executable('server.py',
                            base='Win32GUI',
                            targetName='server.exe',
                            )]
)
