from setuptools import setup, find_packages

setup(name="mess_client_october",
      version="0.0.1",
      description="mess_client_oct",
      author="Anastaziya Tsybusova",
      author_email="stasya17kolomna@gmail.com",
      packages=find_packages(),
      install_requires=['PyQt5', 'sqlalchemy', 'pycryptodome', 'pycryptodomex']
      )
