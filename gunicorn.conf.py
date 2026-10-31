"""One shared in-memory workspace process, with concurrent request threads."""

import os

bind = "0.0.0.0:" + os.environ.get("PORT", "10000")
workers = 1
threads = 4
timeout = 240
accesslog = "-"
errorlog = "-"
