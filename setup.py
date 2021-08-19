from setuptools import find_packages, setup

requirements_file = "requirements.txt"

with open("README.md") as f:
    readme = f.read()

setup(
    name="tap-opensea",
    version="0.1.0",
    description="Singer.io tap for extracting data from OpenSea.io",
    long_description=readme,
    author="Stitch",
    url="http://singer.io",
    classifiers=["Programming Language :: Python :: 3 :: Only"],
    py_modules=["tap_opensea"],
    install_requires=open(requirements_file).readlines(),
    entry_points="""
    [console_scripts]
    tap-opensea=tap_opensea:main
    """,
    packages=find_packages(exclude=["tests"]),
    package_data = {
        "schemas": ["tap_opensea/schemas/*.json"]
    },
    include_package_data=True,
)
