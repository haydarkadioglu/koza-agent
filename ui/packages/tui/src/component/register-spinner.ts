import { getComponentCatalogue } from "@opentui/solid/components"
import { registerSpinner } from "opentui-spinner/solid"

export function registerKozaSpinner() {
  if (!getComponentCatalogue().spinner) registerSpinner()
}
