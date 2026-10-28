import {createAddressSearch} from "./address-search.mjs";
import {addOnlinePlace, showAddressSearch} from "./desk.mjs";

createAddressSearch({onAdd:addOnlinePlace, onShow:showAddressSearch});
