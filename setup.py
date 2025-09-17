#!/usr/bin/env python3
"""Setup script for bridgeme package."""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="bridgeme",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="SSH relay-based reverse shell tool for IT troubleshooting",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/bridgeme",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: System Administrators",
        "Topic :: System :: Systems Administration",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=[
        "paramiko>=2.7.0",
        "click>=7.0",
        "psutil>=5.0.0",
        "colorama>=0.4.0",
    ],
    extras_require={
        "windows": ["pywinpty>=1.1.0"],
        "dev": ["pytest>=6.0", "pytest-cov", "black", "flake8"],
    },
    entry_points={
        "console_scripts": [
            "bridgeme=bridgeme.cli:main",
        ],
    },
)