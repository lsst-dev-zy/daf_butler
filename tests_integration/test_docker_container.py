import contextlib
import os
import tempfile
import unittest

from lsst.daf.butler import Butler
from lsst.daf.butler.tests.utils import MetricTestRepo
from testcontainers.core.container import DockerContainer

TESTDIR = os.path.abspath(os.path.dirname(__file__))


@contextlib.contextmanager
def _run_server_docker():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Ensure the repository directory will be readable inside the container
        os.chmod(temp_dir, 0o755)

        MetricTestRepo(
            root=temp_dir, configFile=os.path.join(TESTDIR, "../tests", "config/basic/butler.yaml")
        )

        port = 8080
        butler_root = "/butler_root"
        docker_image = os.getenv("BUTLER_SERVER_DOCKER_IMAGE")
        if not docker_image:
            raise Exception("BUTLER_SERVER_DOCKER_IMAGE must be set")
        container = (
            DockerContainer(docker_image)
            .with_exposed_ports(port)
            .with_env("BUTLER_SERVER_CONFIG_URI", butler_root)
            .with_volume_mapping(temp_dir, butler_root, "rw")
        )

        with container:
            server_host = container.get_container_host_ip()
            server_port = container.get_exposed_port(port)
            server_url = f"http://{server_host}:{server_port}/api/butler"
            try:
                yield server_url
            finally:
                (stdout, stderr) = container.get_logs()
                if stdout:
                    print("STDOUT:")
                    print(stdout.decode())
                if stderr:
                    print("STDERR:")
                    print(stderr.decode())


class ButlerDockerTestCase(unittest.TestCase):
    """Simple smoke test to ensure the server can start up and respond to
    requests
    """

    @classmethod
    def setUpClass(cls):
        cls.server_uri = cls.enterClassContext(_run_server_docker())

    def test_get_dataset_type(self):
        butler = Butler(self.server_uri)
        dataset_type = butler.get_dataset_type("test_metric_comp")
        self.assertEqual(dataset_type.name, "test_metric_comp")


if __name__ == "__main__":
    unittest.main()