"""
Tests unitarios para el loader de activos.
Verifica carga correcta, validación y errores.
"""
import pytest
import os
import json
import tempfile
from kernel.activos_loader import cargar_activo, listar_activos_disponibles, validar_configuracion_activo


class TestCargarActivo:
    """Tests para la función cargar_activo."""
    
    def test_carga_eurusd_correctamente(self):
        """Verifica que EURUSD se carga con valores esperados."""
        activo = cargar_activo("EURUSD")
        assert activo.simbolo == "EURUSD"
        assert activo.punto == 1e-05
        assert activo.tick_size == 1e-05  # Default = punto
        assert activo.contract_size == 100000
        assert activo.session_open == "00:00"
        assert activo.session_close == "23:59"

    def test_carga_xauusd_correctamente(self):
        """Verifica que XAUUSD se carga correctamente."""
        activo = cargar_activo("XAUUSD")
        assert activo.simbolo == "XAUUSD"
        assert activo.punto == 0.01  # Oro tiene diferente precisión
        # contract_size usa default 100000 si no viene en JSON
        assert activo.contract_size == 100000

    def test_falla_si_activo_no_existe(self):
        """Verifica que lanza ValueError si el archivo no existe."""
        with pytest.raises(ValueError) as exc_info:
            cargar_activo("NOEXISTE")
        assert "No existe configuración" in str(exc_info.value)
        assert "NOEXISTE" in str(exc_info.value)

    def test_falla_si_falta_campo_point(self, tmp_path):
        """Verifica que falla si falta el campo crítico 'point'."""
        # Crear JSON inválido sin 'point'
        json_data = {"simbolo": "TEST", "contract_size": 1000}
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(json_data))
        
        # Usar monkeypatch para interceptar la ruta
        import kernel.activos_loader as loader_module
        original_join = os.path.join
        
        def mock_join(*args):
            if "activos" in args:
                return str(json_file)
            return original_join(*args)
        
        os.path.join = mock_join
        try:
            with pytest.raises(ValueError) as exc_info:
                cargar_activo("TEST")
            assert "Campo 'point' faltante" in str(exc_info.value)
        finally:
            os.path.join = original_join


class TestListarActivos:
    """Tests para listar_activos_disponibles."""
    
    def test_retorna_lista_con_activos_existentes(self):
        """Verifica que retorna lista con activos en directorio."""
        activos = listar_activos_disponibles()
        assert isinstance(activos, list)
        assert "EURUSD" in activos
        assert "XAUUSD" in activos
        assert len(activos) >= 2

    def test_excluye_configs_binary(self, tmp_path):
        """Los JSON *_binary.json no son activos del hub."""
        (tmp_path / "eurusd.json").write_text("{}")
        (tmp_path / "eurusd_binary.json").write_text("{}")
        activos = listar_activos_disponibles(str(tmp_path))
        assert "EURUSD" in activos
        assert "EURUSD_BINARY" not in activos

    def test_retorna_lista_vacia_si_directorio_no_existe(self):
        """Verifica comportamiento con directorio inexistente."""
        activos = listar_activos_disponibles("/no/existe")
        assert activos == []
        assert isinstance(activos, list)

    def test_solo_incluye_archivos_json(self, tmp_path):
        """Verifica que solo incluye archivos .json."""
        # Crear archivos mixtos
        (tmp_path / "valido.json").write_text("{}")
        (tmp_path / "invalido.txt").write_text("texto")
        (tmp_path / "otro.JSON").write_text("{}")  # Mayúsculas
        
        activos = listar_activos_disponibles(str(tmp_path))
        assert "VALIDO" in activos
        assert "INVALIDO" not in activos
        # Nota: .JSON en mayúsculas no se incluye (filter es case-sensitive)


class TestValidarConfiguracion:
    """Tests para validar_configuracion_activo."""
    
    def test_valida_json_correcto(self, tmp_path):
        """Verifica que valida correctamente un JSON válido."""
        json_data = {"simbolo": "TEST", "point": 0.0001}
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(json_data))
        
        resultado = validar_configuracion_activo(str(json_file))
        assert resultado is True

    def test_rechaza_sin_campo_simbolo(self, tmp_path):
        """Verifica que rechaza JSON sin campo 'simbolo'."""
        json_data = {"point": 0.0001}  # Falta simbolo
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(json_data))
        
        resultado = validar_configuracion_activo(str(json_file))
        assert resultado is False

    def test_rechaza_sin_campo_point(self, tmp_path):
        """Verifica que rechaza JSON sin campo 'point'."""
        json_data = {"simbolo": "TEST"}  # Falta point
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(json_data))
        
        resultado = validar_configuracion_activo(str(json_file))
        assert resultado is False

    def test_rechaza_point_no_numerico(self, tmp_path):
        """Verifica que rechaza point no numérico."""
        json_data = {"simbolo": "TEST", "point": "invalido"}
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(json_data))
        
        resultado = validar_configuracion_activo(str(json_file))
        assert resultado is False

    def test_rechaza_point_negativo(self, tmp_path):
        """Verifica que rechaza point negativo."""
        json_data = {"simbolo": "TEST", "point": -0.0001}
        json_file = tmp_path / "test.json"
        json_file.write_text(json.dumps(json_data))
        
        resultado = validar_configuracion_activo(str(json_file))
        assert resultado is False

    def test_rechaza_json_invalido(self, tmp_path):
        """Verifica que maneja JSON mal formado."""
        json_file = tmp_path / "test.json"
        json_file.write_text("{json invalido}")
        
        resultado = validar_configuracion_activo(str(json_file))
        assert resultado is False

    def test_maneja_archivo_inexistente(self, tmp_path):
        """Verifica que maneja archivo que no existe."""
        resultado = validar_configuracion_activo(str(tmp_path / "no_existe.json"))
        assert resultado is False
