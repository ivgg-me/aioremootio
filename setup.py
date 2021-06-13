from setuptools import setup, find_packages
import pathlib

here = pathlib.Path(__file__).parent.resolve()

long_description = (here / 'README.md').read_text(encoding='utf-8')
install_requires = list(val.strip() for val in open(here / 'requirements.txt'))

setup(
    name="aioremootio",
    version="1.0.0.alpha5",
    description="An asynchronous API client library for Remootio (http://www.remootio.com/)",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ivgg-me/aioremootio",
    author="Gergö Gabor Ilyes-Veisz",
    author_email="i@ivgg.me",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Framework :: AsyncIO",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Topic :: Home Automation",
        "Topic :: Software Development :: Libraries"
    ],
    keywords="remootio, client, library, asynchronous",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    install_requires=install_requires,
    project_urls={
        "Bug Tracker": "https://github.com/ivgg-me/aioremootio/issues",
        "Source": "https://github.com/ivgg-me/aioremootio/"
    }
)