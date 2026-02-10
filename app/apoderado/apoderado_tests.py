from .controller import ApoderadoController


def test_index():
    apoderado_controller = ApoderadoController()
    result = apoderado_controller.index()
    assert result == {"message": "Hello, World!"}
