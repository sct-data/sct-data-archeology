.. -*- coding: utf-8; indent-tabs-mode:nil; -*-

###################
SCT Data Archeology
###################


This is quick & dirty code which helps making history.


Usage
#####

0. Have `spinalcordtoolbox` repo around

1. Retrieve URLs from repository:

   .. code:: sh

      python sct-data-urls.py

2. Create repos:

   .. code:: sh

      python sct-data-old2git.py tmp-sct-data-urls/${key}.yml


Design
######

- Walk the SCT history (simplified), and look for URLs in SCT code.

  This is done using AST.

- Build key -> commit -> urls and dump into a YAML file

- Use YAML file to reconstruct a repo in a second pass


