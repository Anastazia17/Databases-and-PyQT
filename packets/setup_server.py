from setuptools import setup, find_packages

setup(name="mess_server_oct",
      version="0.0.1",
      description="mess_server_oct",
      author="Anastaziya Tsybusova",
      author_email="stasya17kolomna@gmail.com",
      packages=find_packages(),
      install_requires=['PyQt5', 'sqlalchemy', 'pycryptodome', 'pycryptodomex']
      )
