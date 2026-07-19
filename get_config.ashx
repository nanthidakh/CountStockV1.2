using System;
using System.Web;
using System.Web.Script.Serialization;
using System.Collections.Generic;

public void ProcessRequest (HttpContext context) {
    context.Response.ContentType = "application/json";
    try {
        var configs = new List<object> {
            new { branch_name = "มาบตาพุด", db_server_ip = "10.1.1.3", db_name = "HWKING_MP", db_user = "sa", db_password = "Hwkingp@ss", count_month = "08/2026", iis_server_ip = context.Request.Url.Host },
            new { branch_name = "บ่อวิน", db_server_ip = "192.168.1.20", db_name = "HWKING_BW", db_user = "sa", db_password = "Hwkingp@ss", count_month = "08/2026", iis_server_ip = context.Request.Url.Host }
        };

        JavaScriptSerializer js = new JavaScriptSerializer();
        context.Response.Write(js.Serialize(configs));
    }
    catch (Exception ex) {
        // หากมี error โค้ดนี้จะส่งรายละเอียดออกมาให้คุณเห็น
        context.Response.Write("{\"error\": \"" + ex.Message.Replace("\"", "'") + "\"}");
    }
}