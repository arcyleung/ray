filegroup(
    name = "example",
    data = glob(["example-*.yaml"]),
    visibility = [
        "//python/ray/tests:__pkg__",
    ],
)

filegroup(
    name = "test_configs",
    data = glob(["tests/*.yaml"]),
    visibility = ["//release:__pkg__"],
)

filegroup(
    name = "default_config",
    srcs = ["defaults.yaml"],
    visibility = ["//visibility:public"],
)
