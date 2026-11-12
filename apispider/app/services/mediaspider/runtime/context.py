from contextvars import ContextVar

source_keyword_var = ContextVar("source_keyword", default="")
request_keyword_var = ContextVar("request_keyword", default="")
crawler_type_var = ContextVar("crawler_type", default="")
creator_profile_var = ContextVar("creator_profile", default=None)
comment_tasks_var = ContextVar("comment_tasks", default=None)
