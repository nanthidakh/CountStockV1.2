<%@ WebHandler Language="C#" Class="get_config" %>
using System;
using System.Web;
using System.Web.Script.Serialization;
using System.Collections.Generic;

// ต้องมีบรรทัดนี้เพื่อให้ IIS รู้จัก Class และ Method
public class get_config : IHttpHandler { 

    public void ProcessRequest (HttpContext context) {
        context.Response.ContentType = "application/json";
        try {
            var configs = new List<object> {
			    new { branch_name = "Bowin", db_server_ip = "10.1.1.3", db_name = "HWKING_BW", db_user = "sa", db_password = "Hwkingp@ss", count_month = "08/2026", iis_server_ip = context.Request.Url.Host }
                new { branch_name = "Maptapud", db_server_ip = "10.1.1.3", db_name = "HWKING_MP", db_user = "sa", db_password = "Hwkingp@ss", count_month = "08/2026", iis_server_ip = context.Request.Url.Host },
            };

            JavaScriptSerializer js = new JavaScriptSerializer();
            context.Response.Write(js.Serialize(configs));
        }
        catch (Exception ex) {
            context.Response.Write("{\"error\": \"" + ex.Message.Replace("\"", "'") + "\"}");
        }
    }

    // ต้องเพิ่มส่วนนี้เพื่อให้ IHttpHandler ทำงานได้สมบูรณ์
    public bool IsReusable {
        get { return false; }
    }
}