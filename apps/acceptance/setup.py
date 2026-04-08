from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

setup(
    name="acceptance",
    version="0.0.1",
    description="承兑汇票全生命周期管理",
    author="台州京泰",
    author_email="dev@tzjingtai.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
