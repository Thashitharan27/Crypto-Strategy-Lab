from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings
from crypto_strategy_lab.gui.chatgpt_connection import (ChatGPTConnectionManager,
    TUNNEL_ARGUMENTS, redact_secrets, tunnel_environment, validate_configuration)

def test_validation_reports_each_missing_item(tmp_path):
    with patch('crypto_strategy_lab.gui.chatgpt_connection.importlib.util.find_spec',return_value=object()):
        errors=validate_configuration(str(tmp_path/'missing.exe'),'',None,tmp_path/'missing-output',0)
    for phrase in ('executable','Tunnel ID','API key','output directory','port'):
        assert any(phrase in error for error in errors)

def test_valid_configuration(tmp_path):
    exe=tmp_path/'tunnel client.exe'; exe.touch(); out=tmp_path/'output'; out.mkdir()
    with patch('crypto_strategy_lab.gui.chatgpt_connection.importlib.util.find_spec',return_value=object()):
        assert validate_configuration(str(exe),'tunnel_example','secret',out,8765)==[]

def test_redaction():
    text=redact_secrets('sk-exampleSecret123 CONTROL_PLANE_API_KEY=another-secret')
    assert 'exampleSecret' not in text and 'another-secret' not in text
    assert text.count('[REDACTED]')==2

def test_tunnel_command_and_environment_do_not_mix_secret():
    secret='super-secret-value'; env=tunnel_environment(secret,'tunnel_example','http://127.0.0.1:8765/mcp')
    assert TUNNEL_ARGUMENTS==['run','--log.level=info','--log.format=struct-text']
    assert secret not in TUNNEL_ARGUMENTS
    assert env.value('CONTROL_PLANE_API_KEY')==secret
    assert env.value('CONTROL_PLANE_TUNNEL_ID')=='tunnel_example'
    assert env.value('MCP_SERVER_URL').endswith('/mcp')

def test_duplicate_start_and_stop_without_processes(qapp,tmp_path):
    manager=ChatGPTConnectionManager(lambda:str(tmp_path)); manager._starting=True
    assert manager.start('client.exe','tunnel','key',8765) is False
    manager._starting=False; manager.stop(); assert manager.state=='Disconnected'

def test_api_key_is_not_a_settings_key(tmp_path):
    settings=QSettings(str(tmp_path/'settings.ini'),QSettings.IniFormat)
    for key,value in {'tunnel_client_path':'client.exe','tunnel_id':'tunnel_x','mcp_port':8765,'auto_start_chatgpt_connection':True}.items(): settings.setValue(key,value)
    settings.sync()
    assert not any('api' in key.lower() or 'credential' in key.lower() for key in settings.allKeys())
    assert 'secret' not in Path(settings.fileName()).read_text()
