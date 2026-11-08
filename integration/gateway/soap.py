"""Tầng tích hợp (ESB) — dàn xếp giao thức SOAP 1.1 <-> REST/JSON.

CatalogService là một web service SOAP (document/literal, có WSDL). Gateway nhận
SOAP envelope, chuyển thành lời gọi REST tới product-service (tìm qua Service Registry),
rồi biến đổi JSON trả về thành XML theo hợp đồng WSDL. Lỗi được trả bằng SOAP Fault.
Đây là hai chức năng điển hình của ESB: protocol mediation và message transformation.
"""
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from common.errors import ApiError

NS = "urn:taphoaxanh:catalog:v1"
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
MAX_BODY = 64 * 1024
OPERATIONS = ("GetCategories", "SearchProducts", "GetProduct")

ET.register_namespace("soap", SOAP_NS)
ET.register_namespace("tns", NS)


class SoapFault(Exception):
    def __init__(self, code, message, detail_code=None):
        super().__init__(message)
        self.code, self.message, self.detail_code = code, message, detail_code


def _q(tag):
    return f"{{{NS}}}{tag}"


def _local(tag):
    return tag.split("}", 1)[-1]


def _envelope(payload):
    env = ET.Element(f"{{{SOAP_NS}}}Envelope")
    body = ET.SubElement(env, f"{{{SOAP_NS}}}Body")
    body.append(payload)
    return '<?xml version="1.0" encoding="utf-8"?>' + ET.tostring(env, encoding="unicode")


def _add(parent, tag, value):
    if value is None:
        return
    el = ET.SubElement(parent, _q(tag))
    el.text = str(value).lower() if isinstance(value, bool) else str(value)


def _product(parent, p, full=False):
    el = ET.SubElement(parent, _q("Product"))
    for tag, key in (("id", "id"), ("sku", "sku"), ("name", "name"), ("category", "category_name"), ("unit", "unit"),
                     ("price", "price"), ("salePrice", "sale_price"), ("finalPrice", "final_price"),
                     ("available", "available"), ("rating", "rating_avg")):
        _add(el, tag, p.get(key))
    if full:
        _add(el, "brand", p.get("brand"))
        _add(el, "barcode", p.get("barcode"))
        _add(el, "description", p.get("description"))
    return el


def _args(op_el):
    return {_local(c.tag): (c.text or "").strip() for c in op_el}


def _int(args, name, default=None, minimum=1, maximum=None):
    raw = args.get(name)
    if raw in (None, ""):
        if default is None:
            raise SoapFault("Client", f"Thiếu tham số {name}", "MISSING_PARAMETER")
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SoapFault("Client", f"Tham số {name} phải là số nguyên", "INVALID_PARAMETER")
    if value < minimum or (maximum and value > maximum):
        raise SoapFault("Client", f"Tham số {name} ngoài phạm vi cho phép", "INVALID_PARAMETER")
    return value


def fault_xml(fault):
    f = ET.Element(f"{{{SOAP_NS}}}Fault")
    ET.SubElement(f, "faultcode").text = f"soap:{fault.code}"
    ET.SubElement(f, "faultstring").text = fault.message
    if fault.detail_code:
        detail = ET.SubElement(f, "detail")
        err = ET.SubElement(detail, _q("ErrorDetail"))
        _add(err, "code", fault.detail_code)
    return _envelope(f)


def handle(body_bytes, product_client):
    """Xử lý một SOAP request. Trả về (http_status, xml)."""
    try:
        if len(body_bytes) > MAX_BODY:
            raise SoapFault("Client", "SOAP message quá lớn", "MESSAGE_TOO_LARGE")
        if b"<!DOCTYPE" in body_bytes.upper() or b"<!ENTITY" in body_bytes.upper():
            raise SoapFault("Client", "Không chấp nhận DTD trong SOAP message", "DTD_NOT_ALLOWED")
        try:
            root = ET.fromstring(body_bytes)
        except ET.ParseError:
            raise SoapFault("Client", "SOAP envelope không phải XML hợp lệ", "MALFORMED_XML")
        if root.tag != f"{{{SOAP_NS}}}Envelope":
            raise SoapFault("Client", "Thiếu soap:Envelope (SOAP 1.1)", "NOT_SOAP")
        body = root.find(f"{{{SOAP_NS}}}Body")
        if body is None or len(body) == 0:
            raise SoapFault("Client", "Thiếu soap:Body hoặc không có thao tác", "EMPTY_BODY")
        op_el = body[0]
        op = _local(op_el.tag)
        if op not in OPERATIONS:
            raise SoapFault("Client", f"Thao tác không được hỗ trợ: {op}", "UNKNOWN_OPERATION")
        args = _args(op_el)
        resp = ET.Element(_q(op + "Response"))

        if op == "GetCategories":
            for c in product_client.get("/api/categories")["items"]:
                el = ET.SubElement(resp, _q("Category"))
                for tag, key in (("id", "id"), ("name", "name"), ("icon", "icon"), ("productCount", "product_count")):
                    _add(el, tag, c.get(key))
        elif op == "SearchProducts":
            params = {"q": args.get("keyword") or None, "page": _int(args, "page", 1),
                      "page_size": _int(args, "pageSize", 10, maximum=50)}
            if args.get("categoryId"):
                params["category_id"] = _int(args, "categoryId")
            data = product_client.get("/api/products", params=params)
            _add(resp, "total", data["total"])
            _add(resp, "page", data["page"])
            _add(resp, "totalPages", data["total_pages"])
            for p in data["items"]:
                _product(resp, p)
        else:  # GetProduct
            pid = _int(args, "productId")
            _product(resp, product_client.get(f"/api/products/{pid}"), full=True)
        return 200, _envelope(resp)
    except SoapFault as f:
        return 500, fault_xml(f)
    except ApiError as e:
        code = "Client" if e.status < 500 else "Server"
        return 500, fault_xml(SoapFault(code, e.message, e.code))


def wsdl(endpoint):
    """Hợp đồng WSDL 1.1 của CatalogService."""
    ops = "".join(f"""
    <wsdl:operation name="{op}">
      <wsdl:input message="tns:{op}Input"/>
      <wsdl:output message="tns:{op}Output"/>
    </wsdl:operation>""" for op in OPERATIONS)
    bindings = "".join(f"""
    <wsdl:operation name="{op}">
      <soap:operation soapAction="{NS}#{op}"/>
      <wsdl:input><soap:body use="literal"/></wsdl:input>
      <wsdl:output><soap:body use="literal"/></wsdl:output>
    </wsdl:operation>""" for op in OPERATIONS)
    messages = "".join(f"""
  <wsdl:message name="{op}Input"><wsdl:part name="parameters" element="tns:{op}"/></wsdl:message>
  <wsdl:message name="{op}Output"><wsdl:part name="parameters" element="tns:{op}Response"/></wsdl:message>""" for op in OPERATIONS)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<wsdl:definitions name="CatalogService" targetNamespace="{NS}"
    xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"
    xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:tns="{NS}">
  <wsdl:documentation>Dịch vụ tra cứu danh mục sản phẩm Tạp Hóa Xanh (SOAP 1.1, document/literal). ESB tại API Gateway chuyển tiếp tới product-service REST.</wsdl:documentation>
  <wsdl:types>
    <xsd:schema targetNamespace="{NS}" elementFormDefault="qualified" xmlns:tns="{NS}">
      <xsd:complexType name="Category">
        <xsd:sequence>
          <xsd:element name="id" type="xsd:int"/>
          <xsd:element name="name" type="xsd:string"/>
          <xsd:element name="icon" type="xsd:string" minOccurs="0"/>
          <xsd:element name="productCount" type="xsd:int"/>
        </xsd:sequence>
      </xsd:complexType>
      <xsd:complexType name="Product">
        <xsd:sequence>
          <xsd:element name="id" type="xsd:int"/>
          <xsd:element name="sku" type="xsd:string"/>
          <xsd:element name="name" type="xsd:string"/>
          <xsd:element name="category" type="xsd:string"/>
          <xsd:element name="unit" type="xsd:string"/>
          <xsd:element name="price" type="xsd:long"/>
          <xsd:element name="salePrice" type="xsd:long" minOccurs="0"/>
          <xsd:element name="finalPrice" type="xsd:long"/>
          <xsd:element name="available" type="xsd:int" minOccurs="0"/>
          <xsd:element name="rating" type="xsd:decimal"/>
          <xsd:element name="brand" type="xsd:string" minOccurs="0"/>
          <xsd:element name="barcode" type="xsd:string" minOccurs="0"/>
          <xsd:element name="description" type="xsd:string" minOccurs="0"/>
        </xsd:sequence>
      </xsd:complexType>
      <xsd:element name="GetCategories"><xsd:complexType><xsd:sequence/></xsd:complexType></xsd:element>
      <xsd:element name="GetCategoriesResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="Category" type="tns:Category" minOccurs="0" maxOccurs="unbounded"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="SearchProducts">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="keyword" type="xsd:string" minOccurs="0"/>
          <xsd:element name="categoryId" type="xsd:int" minOccurs="0"/>
          <xsd:element name="page" type="xsd:int" minOccurs="0"/>
          <xsd:element name="pageSize" type="xsd:int" minOccurs="0"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="SearchProductsResponse">
        <xsd:complexType><xsd:sequence>
          <xsd:element name="total" type="xsd:int"/>
          <xsd:element name="page" type="xsd:int"/>
          <xsd:element name="totalPages" type="xsd:int"/>
          <xsd:element name="Product" type="tns:Product" minOccurs="0" maxOccurs="unbounded"/>
        </xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="GetProduct">
        <xsd:complexType><xsd:sequence><xsd:element name="productId" type="xsd:int"/></xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="GetProductResponse">
        <xsd:complexType><xsd:sequence><xsd:element name="Product" type="tns:Product"/></xsd:sequence></xsd:complexType>
      </xsd:element>
      <xsd:element name="ErrorDetail">
        <xsd:complexType><xsd:sequence><xsd:element name="code" type="xsd:string"/></xsd:sequence></xsd:complexType>
      </xsd:element>
    </xsd:schema>
  </wsdl:types>{messages}
  <wsdl:portType name="CatalogPortType">{ops}
  </wsdl:portType>
  <wsdl:binding name="CatalogSoapBinding" type="tns:CatalogPortType">
    <soap:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/>{bindings}
  </wsdl:binding>
  <wsdl:service name="CatalogService">
    <wsdl:port name="CatalogPort" binding="tns:CatalogSoapBinding">
      <soap:address location="{escape(endpoint)}"/>
    </wsdl:port>
  </wsdl:service>
</wsdl:definitions>
"""
