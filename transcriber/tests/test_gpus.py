from sb_transcriber import gpus


def test_parse() -> None:
    assert gpus.parse("0") == [0]
    assert gpus.parse("1,0, 1") == [0, 1]


def test_worker_command_line() -> None:
    """Each worker gets its own GPU in place of the list, and the worker flag."""
    argv = ["run", "--all", "--gpu", "all", "--model", "large-v3"]
    assert gpus._with_gpu(argv, 1) == [  # pyright: ignore[reportPrivateUsage]
        "run",
        "--all",
        "--model",
        "large-v3",
        "--gpu",
        "1",
        gpus.CHILD_FLAG,
    ]
    assert gpus._with_gpu(["run", "--gpu=0,1", "dune"], 0) == [  # pyright: ignore[reportPrivateUsage]
        "run",
        "dune",
        "--gpu",
        "0",
        gpus.CHILD_FLAG,
    ]
