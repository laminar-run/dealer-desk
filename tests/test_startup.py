import logging
from unittest.mock import Mock

import main


def test_optional_actions_do_not_block_login(monkeypatch, caplog):
    root, login = Mock(), Mock()
    monkeypatch.setattr(main.tk, "Tk", lambda: root)
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main, "seed", lambda: None)
    monkeypatch.setattr(main, "_launch_login", login)
    monkeypatch.setattr("action_control.receiver.start_test_inbox", Mock(side_effect=OSError("inbox unavailable")))
    with caplog.at_level(logging.ERROR):
        main.main()
    login.assert_called_once_with(root)
    root.mainloop.assert_called_once()
    assert "Cannot start optional action tools" in caplog.text
