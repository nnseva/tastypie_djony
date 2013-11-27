#!/usr/bin/env python

import os.path
from setuptools import setup, find_packages

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setupconf = dict(
    name = 'tastypie_djony',
    version = "0.0.2",
    license = 'LGPL',
    url = 'https://github.com/nnseva/tastypie_djony/',
    author = 'Vsevolod Novikov',
    author_email = 'nnseva@gmail.com',
    description = ('Tastypie accelerator using Pony ORM'),
    long_description = read('README.rst'),

    packages = find_packages(),

    install_requires = ['djony>=0.0.1'],

    classifiers = [
        'Intended Audience :: Developers',
        'License :: OSI Approved :: LGPL License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        ],
    zip_safe=False,
    )

if __name__ == '__main__':
    setup(**setupconf)
