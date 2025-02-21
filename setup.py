#!/usr/bin/env python3
import setuptools
import sys

# try:
#    import pip
#    import pip.req
# except ImportError:
#    print("pip module not found.", file=sys.stderr)
#    raise


def forbid_publish():
    argv = sys.argv
    blacklist = ["register", "upload"]

    for command in blacklist:
        if command in argv:
            values = {"command": command}
            print('Command "%(command)s" has been blacklisted, exiting...' % values)
            sys.exit(2)


if __name__ == "__main__":
    forbid_publish()

    with open("README.md", "r") as fh:
        long_description = fh.read()

    setuptools.setup(
        name="oui_extras",
        version="0.1",
        author_email="ohmajesticlama@gmail.com",
        description="Python package to support investment.",
        long_description=long_description,
        # url="https://github.com/pypa/sampleproject",
        packages=setuptools.find_packages(),
        package_data={"openwebui_functions_extras": ["py.typed"]},
        install_requires=[
            "langgraph>=0.2,<0.3",
            "pydantic>=2.10,<3.0",
        ],
        extras_require={
            "dev": [
                "build >= 0.7.0",
                "coverage >= 6.3",
                "flake8 >= 4.0.1",
                "ipdb",
                "ipython",
                "mypy >= 0.931",
                "pytest >= 7.0.1",
                "typeguard >= 2.13.3, < 3.0.0",
            ],
        },
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: MIT License",
            "Operating System :: OS Independent",
        ],
        tests_require=["pytest"],
    )
