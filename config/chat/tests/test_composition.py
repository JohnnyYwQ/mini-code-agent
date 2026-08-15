from unittest import TestCase
from unittest.mock import Mock, patch

from core.agent_runtime import AgentRuntimeConfig

from chat.composition import _production_memory, close_production_memory


class ProductionMemoryLifecycleTests(TestCase):
    def tearDown(self):
        _production_memory.cache_clear()

    @patch("chat.composition.build_memory")
    @patch(
        "chat.composition._agent_config",
        return_value=AgentRuntimeConfig(model="test-model", api_key="test-key"),
    )
    def test_closes_cached_memory_once_and_clears_it(
        self,
        agent_config,
        build_memory,
    ):
        memory = Mock()
        build_memory.return_value = memory
        _production_memory.cache_clear()
        self.assertIs(_production_memory(), memory)

        close_production_memory()
        close_production_memory()

        memory.close.assert_called_once_with()
        self.assertEqual(_production_memory.cache_info().currsize, 0)

    @patch("chat.composition.build_memory")
    def test_does_not_initialize_memory_just_to_close_it(self, build_memory):
        _production_memory.cache_clear()

        close_production_memory()

        build_memory.assert_not_called()
