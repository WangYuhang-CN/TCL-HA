"""Pure modules can be tested without executing the Home Assistant entry point."""

from pathlib import Path
import sys
from types import ModuleType

package = ModuleType("custom_components.tcl_plus")
package.__path__ = [
    str(Path(__file__).resolve().parents[1] / "custom_components/tcl_plus")
]
sys.modules.setdefault("custom_components.tcl_plus", package)
